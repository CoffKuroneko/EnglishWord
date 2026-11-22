
from flask import Flask, request, redirect, url_for, render_template, abort
import sqlite3
from pathlib import Path

app = Flask(__name__)
DB = Path(__file__).with_name('words.db')
STATUS = {0: '未習得', 1: '曖昧', 2: '習得'}


def connect():
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    conn.execute('PRAGMA foreign_keys = ON')
    return conn


def init_db():
    with connect() as conn:
        conn.execute('''CREATE TABLE IF NOT EXISTS words (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            word TEXT NOT NULL,
            meaning TEXT NOT NULL,
            example TEXT NOT NULL DEFAULT '',
            status INTEGER NOT NULL DEFAULT 0
                CHECK(status IN (0,1,2))
        )''')

        conn.execute('''CREATE TABLE IF NOT EXISTS lists (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE
        )''')

        conn.execute('''CREATE TABLE IF NOT EXISTS word_lists (
            word_id INTEGER NOT NULL,
            list_id INTEGER NOT NULL,
            PRIMARY KEY (word_id, list_id),
            FOREIGN KEY (word_id)
                REFERENCES words(id) ON DELETE CASCADE,
            FOREIGN KEY (list_id)
                REFERENCES lists(id) ON DELETE CASCADE
        )''')


def back():
    return redirect(url_for(
        'index',
        q=request.form.get('q', ''),
        status=request.form.get('filter', 'all'),
        list_id=request.form.get('list_filter', 'all')
    ))


@app.get('/')
def index():
    q = request.args.get('q', '').strip()
    status = request.args.get('status', 'all')
    list_id = request.args.get('list_id', 'all')

    sql = '''
        SELECT * FROM words
        WHERE (word LIKE ? OR meaning LIKE ?)
    '''
    params = [f'%{q}%', f'%{q}%']

    if status in ('0', '1', '2'):
        sql += ' AND status = ?'
        params.append(int(status))
    else:
        status = 'all'

    if list_id.isdigit():
        sql += ''' AND id IN (
            SELECT word_id FROM word_lists
            WHERE list_id = ?
        )'''
        params.append(int(list_id))
    else:
        list_id = 'all'

    with connect() as conn:
        words = conn.execute(
            sql + ' ORDER BY word COLLATE NOCASE, id',
            params
        ).fetchall()

        counts = dict(conn.execute(
            'SELECT status, COUNT(*) FROM words GROUP BY status'
        ).fetchall())

        lists = conn.execute(
            'SELECT * FROM lists ORDER BY name'
        ).fetchall()

        relations = conn.execute(
            'SELECT * FROM word_lists'
        ).fetchall()

        memberships = {}

        for row in relations:
            memberships.setdefault(
                row['word_id'], []
            ).append(row['list_id'])

    return render_template(
        'index.html',
        words=words,
        counts=counts,
        statuses=STATUS,
        q=q,
        selected=status,
        lists=lists,
        selected_list=list_id,
        memberships=memberships
    )


def fields():
    word = request.form.get('word', '').strip()
    meaning = request.form.get('meaning', '').strip()
    example = request.form.get('example', '').strip()

    if not word or not meaning:
        abort(400, '単語と意味を入力してください。')

    return word, meaning, example


def save_word_lists(conn, word_id):
    list_ids = request.form.getlist(
        'list_ids', type=int
    )

    conn.execute(
        'DELETE FROM word_lists WHERE word_id=?',
        (word_id,)
    )

    for list_id in set(list_ids):
        conn.execute('''
            INSERT INTO word_lists(word_id, list_id)
            SELECT ?, id FROM lists WHERE id=?
        ''', (word_id, list_id))


@app.post('/add')
def add():
    with connect() as conn:
        cursor = conn.execute(
            '''INSERT INTO words(word, meaning, example)
               VALUES (?, ?, ?)''',
            fields()
        )

        save_word_lists(conn, cursor.lastrowid)

    return back()


@app.post('/edit/<int:word_id>')
def edit(word_id):
    with connect() as conn:
        cursor = conn.execute(
            '''UPDATE words
               SET word=?, meaning=?, example=?
               WHERE id=?''',
            (*fields(), word_id)
        )

        if cursor.rowcount == 0:
            abort(404)

        save_word_lists(conn, word_id)

    return back()


@app.post('/status/<int:word_id>')
def change_status(word_id):
    status = request.form.get('status', type=int)

    if status not in STATUS:
        abort(400)

    with connect() as conn:
        conn.execute(
            'UPDATE words SET status=? WHERE id=?',
            (status, word_id)
        )

    return back()


@app.post('/delete/<int:word_id>')
def delete(word_id):
    with connect() as conn:
        conn.execute(
            'DELETE FROM words WHERE id=?',
            (word_id,)
        )

    return back()


@app.post('/lists/add')
def add_list():
    name = request.form.get('name', '').strip()

    if not name:
        abort(400, 'リスト名を入力してください。')

    with connect() as conn:
        conn.execute(
            'INSERT OR IGNORE INTO lists(name) VALUES (?)',
            (name,)
        )

    return back()


@app.post('/lists/delete/<int:list_id>')
def delete_list(list_id):
    with connect() as conn:
        conn.execute(
            'DELETE FROM lists WHERE id=?',
            (list_id,)
        )

    return redirect(url_for('index'))


init_db()

if __name__ == '__main__':
    app.run(
        host='0.0.0.0',
        port=5003,
        debug=False
    )
