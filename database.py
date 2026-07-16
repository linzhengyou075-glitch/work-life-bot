from pathlib import Path
import sqlite3

DB_PATH = Path("data/work_life.db")

def connect():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(DB_PATH)
    db.row_factory = sqlite3.Row
    return db

def init_db():
    with connect() as db:
        db.executescript(
            '''
            CREATE TABLE IF NOT EXISTS users (
                line_user_id TEXT PRIMARY KEY,
                display_name TEXT NOT NULL,
                picture_url TEXT,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                last_login_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS shifts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                work_date TEXT NOT NULL UNIQUE,
                store_code TEXT NOT NULL CHECK(store_code IN ('B','C','X')),
                shift_type TEXT NOT NULL CHECK(shift_type IN ('late','night','off')),
                note TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS work_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                work_date TEXT NOT NULL,
                store_code TEXT NOT NULL CHECK(store_code IN ('B','C')),
                category TEXT NOT NULL CHECK(category IN ('handover','shortage','note')),
                title TEXT NOT NULL,
                content TEXT NOT NULL DEFAULT '',
                amount INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS tasks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                due_date TEXT,
                note TEXT NOT NULL DEFAULT '',
                is_done INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                completed_at TEXT
            );
            '''
        )

def upsert_user(line_user_id, display_name, picture_url):
    with connect() as db:
        db.execute(
            '''
            INSERT INTO users(line_user_id, display_name, picture_url)
            VALUES (?, ?, ?)
            ON CONFLICT(line_user_id) DO UPDATE SET
                display_name=excluded.display_name,
                picture_url=excluded.picture_url,
                last_login_at=CURRENT_TIMESTAMP
            ''',
            (line_user_id, display_name, picture_url),
        )

def list_shifts():
    with connect() as db:
        rows = db.execute(
            "SELECT id, work_date, store_code, shift_type, note FROM shifts ORDER BY work_date DESC"
        ).fetchall()
    return [dict(r) for r in rows]

def upsert_shift(work_date, store_code, shift_type, note=""):
    with connect() as db:
        db.execute(
            '''
            INSERT INTO shifts(work_date, store_code, shift_type, note)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(work_date) DO UPDATE SET
                store_code=excluded.store_code,
                shift_type=excluded.shift_type,
                note=excluded.note,
                updated_at=CURRENT_TIMESTAMP
            ''',
            (work_date, store_code, shift_type, note),
        )

def get_today_shift(work_date):
    with connect() as db:
        row = db.execute(
            "SELECT work_date, store_code, shift_type, note FROM shifts WHERE work_date=?",
            (work_date,),
        ).fetchone()
    return dict(row) if row else None

def add_work_log(work_date, store_code, category, title, content="", amount=0):
    with connect() as db:
        db.execute(
            '''
            INSERT INTO work_logs(work_date, store_code, category, title, content, amount)
            VALUES (?, ?, ?, ?, ?, ?)
            ''',
            (work_date, store_code, category, title, content, amount),
        )

def list_work_logs(limit=50):
    with connect() as db:
        rows = db.execute(
            '''
            SELECT id, work_date, store_code, category, title, content, amount, created_at
            FROM work_logs
            ORDER BY work_date DESC, id DESC
            LIMIT ?
            ''',
            (limit,),
        ).fetchall()
    return [dict(r) for r in rows]

def delete_work_log(log_id):
    with connect() as db:
        db.execute("DELETE FROM work_logs WHERE id=?", (log_id,))

def add_task(title, due_date=None, note=""):
    with connect() as db:
        db.execute(
            "INSERT INTO tasks(title, due_date, note) VALUES (?, ?, ?)",
            (title, due_date or None, note),
        )

def list_tasks(show_done=True):
    sql = '''
        SELECT id, title, due_date, note, is_done, created_at, completed_at
        FROM tasks
    '''
    if not show_done:
        sql += " WHERE is_done=0"
    sql += " ORDER BY is_done ASC, COALESCE(due_date, '9999-12-31') ASC, id DESC"
    with connect() as db:
        rows = db.execute(sql).fetchall()
    return [dict(r) for r in rows]

def toggle_task(task_id):
    with connect() as db:
        row = db.execute("SELECT is_done FROM tasks WHERE id=?", (task_id,)).fetchone()
        if not row:
            return
        new_value = 0 if row["is_done"] else 1
        db.execute(
            '''
            UPDATE tasks
            SET is_done=?,
                completed_at=CASE WHEN ?=1 THEN CURRENT_TIMESTAMP ELSE NULL END
            WHERE id=?
            ''',
            (new_value, new_value, task_id),
        )

def delete_task(task_id):
    with connect() as db:
        db.execute("DELETE FROM tasks WHERE id=?", (task_id,))

def dashboard_counts():
    with connect() as db:
        pending = db.execute("SELECT COUNT(*) AS c FROM tasks WHERE is_done=0").fetchone()["c"]
        logs = db.execute("SELECT COUNT(*) AS c FROM work_logs").fetchone()["c"]
        shortages = db.execute(
            "SELECT COALESCE(SUM(amount),0) AS total FROM work_logs WHERE category='shortage'"
        ).fetchone()["total"]
    return {"pending_tasks": pending, "work_logs": logs, "shortage_total": shortages}
