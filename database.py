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
            "SELECT id, work_date, store_code, shift_type, note FROM shifts ORDER BY work_date"
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
