import sqlite3
import json
from datetime import datetime
import io
import os
import pandas as pd
from flask import (
    Flask, g, render_template, request, redirect, url_for,
    session, send_file, flash
)

# -------------------------
# Config
# -------------------------
APP_SECRET = 'change_this_secret_for_prod'
DB_PATH = os.path.join(os.path.dirname(__file__), 'data.db')
ADMIN_USERNAME = 'RamG'
ADMIN_PASSWORD = 'Ram.v@123'

app = Flask(__name__)
app.secret_key = APP_SECRET


# -------------------------
# Database helpers
# -------------------------
def get_db():
    db = getattr(g, '_database', None)
    if db is None:
        db = g._database = sqlite3.connect(DB_PATH)
        db.row_factory = sqlite3.Row
    return db


@app.teardown_appcontext
def close_connection(exception):
    db = getattr(g, '_database', None)
    if db is not None:
        db.close()


def init_db():
    db = get_db()
    cur = db.cursor()
    cur.execute('''
        CREATE TABLE IF NOT EXISTS sections (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            description TEXT
        )
    ''')
    cur.execute('''
        CREATE TABLE IF NOT EXISTS questions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            section_id INTEGER NOT NULL,
            text TEXT NOT NULL,
            options TEXT NOT NULL,
            correct_option INTEGER NOT NULL,
            FOREIGN KEY(section_id) REFERENCES sections(id)
        )
    ''')
    cur.execute('''
        CREATE TABLE IF NOT EXISTS submissions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            section_id INTEGER NOT NULL,
            name TEXT,
            email TEXT,
            timestamp TEXT NOT NULL,
            FOREIGN KEY(section_id) REFERENCES sections(id)
        )
    ''')
    cur.execute('''
        CREATE TABLE IF NOT EXISTS answers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            submission_id INTEGER NOT NULL,
            question_id INTEGER NOT NULL,
            selected_option INTEGER NOT NULL,
            is_correct INTEGER NOT NULL,
            FOREIGN KEY(submission_id) REFERENCES submissions(id),
            FOREIGN KEY(question_id) REFERENCES questions(id)
        )
    ''')
    db.commit()


with app.app_context():
    init_db()


# -------------------------
# Utility
# -------------------------
def admin_required(fn):
    from functools import wraps
    @wraps(fn)
    def wrapper(*args, **kwargs):
        if not session.get('admin'):
            flash('Admin login required')
            return redirect(url_for('admin_login'))
        return fn(*args, **kwargs)
    return wrapper


# -------------------------
# Public routes
# -------------------------
@app.route('/')
def home():
    db = get_db()
    sections = db.execute('SELECT * FROM sections').fetchall()
    return render_template('home.html', sections=sections)


@app.route('/section/<int:section_id>')
def section_page(section_id):
    db = get_db()
    section = db.execute('SELECT * FROM sections WHERE id=?', (section_id,)).fetchone()
    if not section:
        return 'Section not found', 404

    qrows = db.execute('SELECT * FROM questions WHERE section_id=?', (section_id,)).fetchall()
    questions = []
    for q in qrows:
        questions.append({
            'id': q['id'],
            'text': q['text'],
            'options': json.loads(q['options'])
        })

    return render_template('section.html', section=section, questions=questions)


@app.route('/submit/<int:section_id>', methods=['POST'])
def submit_section(section_id):
    db = get_db()
    section = db.execute('SELECT * FROM sections WHERE id=?', (section_id,)).fetchone()
    if not section:
        return 'Section not found', 404

    name = request.form.get('name', '')
    email = request.form.get('email', '')
    # format timestamp in dd-mm-yyyy, HH:MM:SS
    timestamp = datetime.now().strftime("%d-%m-%Y, %H:%M:%S")

    cur = db.cursor()
    cur.execute(
        'INSERT INTO submissions (section_id, name, email, timestamp) VALUES (?,?,?,?)',
        (section_id, name, email, timestamp)
    )
    submission_id = cur.lastrowid

    questions = db.execute('SELECT * FROM questions WHERE section_id=?', (section_id,)).fetchall()
    total = 0
    correct_count = 0

    for q in questions:
        qid = q['id']
        selected = request.form.get(f'q_{qid}')
        try:
            selected_idx = int(selected) if selected is not None else -1
        except ValueError:
            selected_idx = -1

        is_correct = 1 if selected_idx == q['correct_option'] else 0

        cur.execute(
            'INSERT INTO answers (submission_id, question_id, selected_option, is_correct) VALUES (?,?,?,?)',
            (submission_id, qid, selected_idx, is_correct)
        )

        total += 1
        correct_count += is_correct

    db.commit()

    rows = db.execute('''
        SELECT q.text, q.options, q.correct_option, a.selected_option, a.is_correct
        FROM questions q
        JOIN answers a ON q.id = a.question_id
        WHERE a.submission_id=?
    ''', (submission_id,)).fetchall()

    details = []
    for r in rows:
        opts = json.loads(r['options'])
        sel_idx = r['selected_option']
        correct_idx = r['correct_option']
        details.append({
            'question_text': r['text'],
            'selected_text': opts[sel_idx] if 0 <= sel_idx < len(opts) else 'No answer',
            'correct_text': opts[correct_idx] if 0 <= correct_idx < len(opts) else 'N/A',
            'is_correct': bool(r['is_correct'])
        })

    submission = db.execute('SELECT * FROM submissions WHERE id=?', (submission_id,)).fetchone()
    return render_template(
        'result.html',
        submission=submission,
        total=total,
        correct=correct_count,
        wrong=total - correct_count,
        details=details
    )


# -------------------------
# Admin routes
# -------------------------
@app.route('/admin/login', methods=['GET', 'POST'])
def admin_login():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        if username == ADMIN_USERNAME and password == ADMIN_PASSWORD:
            session['admin'] = True
            flash('Logged in as admin')
            return redirect(url_for('admin_dashboard'))
        else:
            flash('Invalid credentials')
    return render_template('admin_login.html')


@app.route('/admin/logout')
def admin_logout():
    session.pop('admin', None)
    flash('Logged out')
    return redirect(url_for('home'))


@app.route('/admin/dashboard')
@admin_required
def admin_dashboard():
    db = get_db()
    sections = db.execute('SELECT * FROM sections').fetchall()
    return render_template('admin_dashboard.html', sections=sections)


@app.route('/admin/section/create', methods=['GET', 'POST'])
@admin_required
def create_section():
    if request.method == 'POST':
        name = request.form.get('name')
        desc = request.form.get('description')
        db = get_db()
        db.execute('INSERT INTO sections (name, description) VALUES (?,?)', (name, desc))
        db.commit()
        flash('Section created')
        return redirect(url_for('admin_dashboard'))
    return render_template('create_section.html')


@app.route('/admin/section/<int:section_id>/questions', methods=['GET', 'POST'])
@admin_required
def add_question(section_id):
    db = get_db()
    section = db.execute('SELECT * FROM sections WHERE id=?', (section_id,)).fetchone()
    if not section:
        return 'Section not found', 404

    if request.method == 'POST':
        text = request.form.get('text')
        opts = [request.form.get(f'opt_{i}') for i in range(4)]
        try:
            correct = int(request.form.get('correct')) - 1
        except (ValueError, TypeError):
            correct = 0
        db.execute(
            'INSERT INTO questions (section_id, text, options, correct_option) VALUES (?,?,?,?)',
            (section_id, text, json.dumps(opts), correct)
        )
        db.commit()
        flash('Question added')
        return redirect(url_for('add_question', section_id=section_id))

    qrows = db.execute('SELECT * FROM questions WHERE section_id=?', (section_id,)).fetchall()
    questions = []
    for q in qrows:
        questions.append({
            'id': q['id'],
            'text': q['text'],
            'options': json.loads(q['options']),
            'correct_option': q['correct_option']
        })

    return render_template('add_question.html', section=section, questions=questions)


@app.route('/admin/submissions')
@admin_required
def view_submissions():
    db = get_db()
    subs = db.execute('''
        SELECT sb.*, sec.name as section_name 
        FROM submissions sb 
        JOIN sections sec ON sb.section_id=sec.id 
        ORDER BY sb.id DESC
    ''').fetchall()
    return render_template('view_submissions.html', subs=subs)


@app.route('/admin/download')
@admin_required
def download_reports():
    db = get_db()
    summary_rows, detail_rows = [], []

    subs = db.execute('''
        SELECT sb.*, sec.name as section_name 
        FROM submissions sb 
        JOIN sections sec ON sb.section_id=sec.id
    ''').fetchall()

    for s in subs:
        answers = db.execute('''
            SELECT a.*, q.text as qtext, q.options as qoptions, q.correct_option
            FROM answers a 
            JOIN questions q ON a.question_id=q.id
            WHERE a.submission_id=?
        ''', (s['id'],)).fetchall()

        total = len(answers)
        correct = sum(a['is_correct'] for a in answers)
        wrong = total - correct

        summary_rows.append({
            'Submission ID': s['id'],
            'Section': s['section_name'],
            'Name': s['name'],
            'Email': s['email'],
            'Timestamp': s['timestamp'],
            'Total': total,
            'Correct': correct,
            'Wrong': wrong
        })

        for a in answers:
            opts = json.loads(a['qoptions'])
            sel_idx, correct_idx = a['selected_option'], a['correct_option']
            detail_rows.append({
                'Submission ID': s['id'],
                'Question': a['qtext'],
                'Selected Option': opts[sel_idx] if 0 <= sel_idx < len(opts) else 'No answer',
                'Correct Option': opts[correct_idx] if 0 <= correct_idx < len(opts) else 'N/A',
                'Is Correct': a['is_correct']
            })

    buffer = io.BytesIO()
    with pd.ExcelWriter(buffer, engine='openpyxl') as writer:
        pd.DataFrame(summary_rows).to_excel(writer, sheet_name='Summary', index=False)
        pd.DataFrame(detail_rows).to_excel(writer, sheet_name='Details', index=False)

    buffer.seek(0)
    return send_file(
        buffer,
        as_attachment=True,
        download_name='submissions_report.xlsx',
        mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
    )


# -------------------------
# Run
# -------------------------
if __name__ == '__main__':
    app.run(debug=True)
