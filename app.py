from flask import Flask, request, redirect, url_for, render_template, abort
import sqlite3
from pathlib import Path

app = Flask(__name__)
DB = Path(__file__).with_name('words.db')
STATUS = {0: '未習得', 1: '曖昧', 2: '習得'}

def connect():
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    with connect() as conn:
        conn.execute('''CREATE TABLE IF NOT EXISTS words (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            word TEXT NOT NULL,
            meaning TEXT NOT NULL,
            example TEXT NOT NULL DEFAULT '',
            status INTEGER NOT NULL DEFAULT 0 CHECK(status IN (0,1,2))
        )''')

def back():
    return redirect(url_for('index', q=request.form.get('q',''), status=request.form.get('filter','all')))

@app.get('/')
def index():
    q = request.args.get('q','').strip()
    status = request.args.get('status','all')
    sql = 'SELECT * FROM words WHERE (word LIKE ? OR meaning LIKE ?)'
    params = [f'%{q}%', f'%{q}%']
    if status in ('0','1','2'):
        sql += ' AND status = ?'
        params.append(int(status))
    else:
        status = 'all'
    with connect() as conn:
        words = conn.execute(sql + ' ORDER BY word COLLATE NOCASE, id', params).fetchall()
        counts = dict(conn.execute('SELECT status, COUNT(*) FROM words GROUP BY status').fetchall())
    return render_template('index.html', words=words, counts=counts, statuses=STATUS, q=q, selected=status)

def fields():
    word = request.form.get('word','').strip()
    meaning = request.form.get('meaning','').strip()
    example = request.form.get('example','').strip()
    if not word or not meaning:
        abort(400, '単語と意味を入力してください。')
    return word, meaning, example

@app.post('/add')
def add():
    with connect() as conn:
        conn.execute('INSERT INTO words(word, meaning, example) VALUES (?, ?, ?)', fields())
    return redirect(url_for('index'))

@app.post('/edit/<int:word_id>')
def edit(word_id):
    with connect() as conn:
        conn.execute('UPDATE words SET word=?, meaning=?, example=? WHERE id=?', (*fields(),word_id))
    return back()

@app.post('/status/<int:word_id>')
def change_status(word_id):
    status = request.form.get('status', type=int)
    if status not in STATUS:
        abort(400)
    with connect() as conn:
        conn.execute('UPDATE words SET status=? WHERE id=?', (status,word_id))
    return back()

@app.post('/delete/<int:word_id>')
def delete(word_id):
    with connect() as conn:
        conn.execute('DELETE FROM words WHERE id=?', (word_id,))
    return back()

init_db()
if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5003, debug=False)
