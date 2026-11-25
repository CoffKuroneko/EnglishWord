
from flask import (
    Flask, request, redirect, url_for,
    render_template, abort, Response, jsonify
)
import sqlite3
from pathlib import Path
import csv
import io

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
            phonetic TEXT NOT NULL DEFAULT '',
            status INTEGER NOT NULL DEFAULT 0
                CHECK(status IN (0,1,2))
        )''')

        # 既存DBへの発音記号カラム追加
        columns = {
            row['name']
            for row in conn.execute(
                'PRAGMA table_info(words)'
            )
        }

        if 'phonetic' not in columns:
            conn.execute('''
                ALTER TABLE words
                ADD COLUMN phonetic TEXT NOT NULL DEFAULT ''
            ''')

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


def back(**kwargs):
    return redirect(url_for(
        'index',
        q=request.form.get('q', ''),
        status=request.form.get('filter', 'all'),
        list_id=request.form.get('list_filter', 'all'),
        **kwargs
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
        memberships=memberships,
        csv_result=request.args.get('csv_result', '')
    )


def fields():
    word = request.form.get('word', '').strip()
    meaning = request.form.get('meaning', '').strip()
    example = request.form.get('example', '').strip()
    phonetic = request.form.get('phonetic', '').strip()

    if not word or not meaning:
        abort(400, '単語と意味を入力してください。')

    return word, meaning, example, phonetic


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


def word_exists(conn, word, exclude_id=None):
    key = word.strip().casefold()
    return any(
        row['word'].strip().casefold() == key
        for row in conn.execute(
            'SELECT id, word FROM words'
        )
        if row['id'] != exclude_id
    )


@app.post('/add')
def add():
    data = fields()
    with connect() as conn:
        conn.execute('BEGIN IMMEDIATE')

        if word_exists(conn, data[0]):
            return back(csv_result='すでに登録されています。')

        cursor = conn.execute(
            """INSERT INTO words(word, meaning, example, phonetic)
               VALUES (?, ?, ?, ?)""",
            data
        )
        save_word_lists(conn, cursor.lastrowid)

    return back()


@app.post('/edit/<int:word_id>')
def edit(word_id):
    data = fields()
    with connect() as conn:
        conn.execute('BEGIN IMMEDIATE')

        if not conn.execute(
            'SELECT id FROM words WHERE id=?', (word_id,)
        ).fetchone():
            abort(404)

        if word_exists(conn, data[0], exclude_id=word_id):
            return back(csv_result='すでに登録されています。')

        conn.execute(
            """UPDATE words
               SET word=?, meaning=?, example=?, phonetic=?
               WHERE id=?""",
            (*data, word_id)
        )
        save_word_lists(conn, word_id)

    return back(_anchor=f'word-{word_id}')


@app.post('/status/<int:word_id>')
def change_status(word_id):
    status = request.form.get('status', type=int)
    if status not in STATUS:
        abort(400)
    with connect() as conn:
        cursor = conn.execute(
            'UPDATE words SET status=? WHERE id=?', (status, word_id)
        )
        if cursor.rowcount == 0:
            abort(404)
        counts = dict(conn.execute(
            'SELECT status, COUNT(*) FROM words GROUP BY status'
        ).fetchall())
    if request.headers.get('X-Requested-With') == 'fetch':
        return jsonify(counts=counts)
    return back()


@app.post('/delete/<int:word_id>')
def delete(word_id):
    with connect() as conn:
        cursor = conn.execute('DELETE FROM words WHERE id=?', (word_id,))
        if cursor.rowcount == 0:
            abort(404)
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


# ========================================
# CSVインポート
# ========================================

@app.post('/csv/import')
def import_csv():
    file = request.files.get('csv_file')

    if not file or not file.filename:
        return back(csv_result='CSVファイルを選択してください。')

    if not file.filename.lower().endswith('.csv'):
        return back(csv_result='CSVファイルを指定してください。')

    # ファイルサイズ上限：5MB
    limit = 5 * 1024 * 1024
    raw = file.stream.read(limit + 1)

    if len(raw) > limit:
        return back(csv_result='ファイルサイズが5MBを超えています。')

    try:
        content = raw.decode('utf-8-sig')
    except UnicodeDecodeError:
        return back(csv_result='UTF-8形式のCSVを指定してください。')

    reader = csv.DictReader(
        io.StringIO(content, newline=''),
        strict=True
    )

    added = 0
    skipped = 0
    invalid = 0

    try:
        headers = reader.fieldnames

        if not headers:
            return back(csv_result='CSVが空です。')

        reader.fieldnames = [
            name.strip().lower()
            for name in headers
        ]

        if len(set(reader.fieldnames)) != len(reader.fieldnames):
            return back(csv_result='CSVの列名が重複しています。')

        if not {'word', 'meaning'}.issubset(reader.fieldnames):
            return back(
                csv_result='wordとmeaningの列が必要です。'
            )

        with connect() as conn:

            # 同時書き込みによる重複登録を防止
            conn.execute('BEGIN IMMEDIATE')

            existing = {
                row['word'].strip().casefold()
                for row in conn.execute(
                    'SELECT word FROM words'
                )
            }

            for row in reader:

                if None in row:
                    invalid += 1
                    continue

                word = (row.get('word') or '').strip()
                meaning = (row.get('meaning') or '').strip()
                example = (row.get('example') or '').strip()
                phonetic = (row.get('phonetic') or '').strip()

                if not word or not meaning:
                    invalid += 1
                    continue

                key = word.casefold()

                if key in existing:
                    skipped += 1
                    continue

                cursor = conn.execute('''
                    INSERT INTO words(
                        word,
                        meaning,
                        example,
                        phonetic,
                        status
                    )
                    VALUES (?, ?, ?, ?, 0)
                ''', (
                    word,
                    meaning,
                    example,
                    phonetic
                ))

                save_word_lists(
                    conn,
                    cursor.lastrowid
                )

                existing.add(key)
                added += 1

    except csv.Error:
        return back(
            csv_result='CSVの形式が不正です。登録を中止しました。'
        )

    return back(
        csv_result=(
            f'新規登録：{added}件 / '
            f'重複スキップ：{skipped}件 / '
            f'入力不備：{invalid}件'
        )
    )


# ========================================
# CSVエクスポート
# ========================================

@app.get('/csv/export')
def export_csv():
    list_id = request.args.get('list_id', 'all')

    sql = '''
        SELECT word, phonetic, meaning, example
        FROM words
    '''

    params = []

    if list_id.isdigit():
        sql += '''
            WHERE id IN (
                SELECT word_id
                FROM word_lists
                WHERE list_id=?
            )
        '''
        params.append(int(list_id))

    sql += ' ORDER BY word COLLATE NOCASE, id'

    with connect() as conn:
        rows = conn.execute(
            sql, params
        ).fetchall()

    output = io.StringIO(newline='')
    writer = csv.writer(output)

    writer.writerow([
        'word',
        'phonetic',
        'meaning',
        'example'
    ])

    for row in rows:
        writer.writerow([
            row['word'],
            row['phonetic'],
            row['meaning'],
            row['example']
        ])

    # Excelでの文字化け対策
    content = output.getvalue().encode('utf-8-sig')

    return Response(
        content,
        content_type='text/csv; charset=utf-8',
        headers={
            'Content-Disposition':
                'attachment; filename="english_words.csv"'
        }
    )


init_db()

if __name__ == '__main__':
    app.run(
        host='0.0.0.0',
        port=5003,
        debug=False
    )
