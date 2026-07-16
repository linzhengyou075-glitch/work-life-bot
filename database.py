from pathlib import Path
import os
import sqlite3
from datetime import datetime

def _db_path():
    custom = os.getenv("WORK_LIFE_DB_PATH", "").strip()
    if custom:
        return Path(custom)
    render_disk = Path("/var/data")
    if render_disk.exists() and os.access(render_disk, os.W_OK):
        return render_disk / "worklife.db"
    return Path("data/worklife.db")

DB_PATH = _db_path()

def connect():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(DB_PATH)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys=ON")
    return db

def _columns(db, table):
    return {row["name"] for row in db.execute(f"PRAGMA table_info({table})").fetchall()}

def _add_column(db, table, definition):
    name = definition.split()[0]
    if name not in _columns(db, table):
        db.execute(f"ALTER TABLE {table} ADD COLUMN {definition}")

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

            CREATE TABLE IF NOT EXISTS shift_types (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL UNIQUE,
                store_code TEXT NOT NULL DEFAULT 'C',
                start_time TEXT NOT NULL,
                end_time TEXT NOT NULL,
                color TEXT NOT NULL DEFAULT '#8f7aea',
                icon TEXT NOT NULL DEFAULT '🌙',
                template_id INTEGER,
                is_active INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS shifts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                work_date TEXT NOT NULL UNIQUE,
                store_code TEXT NOT NULL DEFAULT 'C',
                shift_type TEXT NOT NULL DEFAULT 'night',
                shift_type_id INTEGER,
                overtime INTEGER NOT NULL DEFAULT 0,
                overtime_end TEXT,
                note TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS work_templates (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL UNIQUE,
                description TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS work_template_items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                template_id INTEGER NOT NULL,
                title TEXT NOT NULL,
                scheduled_time TEXT,
                category TEXT NOT NULL DEFAULT 'work',
                sort_order INTEGER NOT NULL DEFAULT 0,
                is_required INTEGER NOT NULL DEFAULT 1,
                remind_once INTEGER NOT NULL DEFAULT 1,
                show_carousel INTEGER NOT NULL DEFAULT 1,
                FOREIGN KEY(template_id) REFERENCES work_templates(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS daily_work_items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                work_date TEXT NOT NULL,
                shift_id INTEGER,
                template_item_id INTEGER,
                title TEXT NOT NULL,
                scheduled_time TEXT,
                category TEXT NOT NULL DEFAULT 'work',
                is_done INTEGER NOT NULL DEFAULT 0,
                completed_at TEXT,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(work_date, template_item_id)
            );

            CREATE TABLE IF NOT EXISTS attendance (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                work_date TEXT NOT NULL UNIQUE,
                shift_id INTEGER,
                check_in_at TEXT,
                check_out_at TEXT,
                note TEXT NOT NULL DEFAULT '',
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS inventory_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                work_date TEXT NOT NULL UNIQUE,
                arrived_at TEXT,
                completed_at TEXT,
                note TEXT NOT NULL DEFAULT '',
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS work_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                work_date TEXT NOT NULL,
                store_code TEXT NOT NULL DEFAULT 'C',
                category TEXT NOT NULL,
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

            CREATE TABLE IF NOT EXISTS reminders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                reminder_type TEXT NOT NULL DEFAULT 'custom',
                remind_date TEXT NOT NULL,
                remind_time TEXT NOT NULL,
                related_url TEXT NOT NULL DEFAULT '/dashboard',
                note TEXT NOT NULL DEFAULT '',
                line_push INTEGER NOT NULL DEFAULT 1,
                show_carousel INTEGER NOT NULL DEFAULT 1,
                sent_at TEXT,
                is_done INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS notification_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                content TEXT NOT NULL DEFAULT '',
                notification_type TEXT NOT NULL DEFAULT 'system',
                status TEXT NOT NULL DEFAULT 'sent',
                sent_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS health_records (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                record_date TEXT NOT NULL UNIQUE,
                steps INTEGER NOT NULL DEFAULT 0,
                heart_rate INTEGER NOT NULL DEFAULT 0,
                sleep_minutes INTEGER NOT NULL DEFAULT 0,
                calories INTEGER NOT NULL DEFAULT 0,
                water_ml INTEGER NOT NULL DEFAULT 0,
                weight REAL NOT NULL DEFAULT 0,
                note TEXT NOT NULL DEFAULT '',
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS finance_records (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                record_date TEXT NOT NULL,
                record_type TEXT NOT NULL CHECK(record_type IN ('income','expense')),
                category TEXT NOT NULL DEFAULT '其他',
                title TEXT NOT NULL,
                amount INTEGER NOT NULL DEFAULT 0,
                note TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS personal_cards (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                card_type TEXT NOT NULL UNIQUE,
                label TEXT NOT NULL,
                barcode_value TEXT NOT NULL DEFAULT '',
                note TEXT NOT NULL DEFAULT '',
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS app_settings (
                setting_key TEXT PRIMARY KEY,
                setting_value TEXT NOT NULL DEFAULT '',
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            '''
        )
        # 舊資料表相容：只補欄位，不刪資料
        _add_column(db, "shifts", "shift_type_id INTEGER")
        _add_column(db, "shifts", "overtime INTEGER NOT NULL DEFAULT 0")
        _add_column(db, "shifts", "overtime_end TEXT")
        seed_defaults(db)

def seed_defaults(db):
    templates = [
        ("大夜班工作攻略", "大夜班自動套用工作事項"),
        ("晚班基本工作", "晚班預設工作事項"),
    ]
    for name, desc in templates:
        db.execute("INSERT OR IGNORE INTO work_templates(name, description) VALUES (?,?)", (name, desc))

    night_id = db.execute("SELECT id FROM work_templates WHERE name='大夜班工作攻略'").fetchone()["id"]
    late_id = db.execute("SELECT id FROM work_templates WHERE name='晚班基本工作'").fetchone()["id"]

    night_items = [
        ("列管、找零金3000對點", "23:00", 10),
        ("填寫品保", "23:00", 20),
        ("廢棄FF區鮮食商品", "23:00", 30),
        ("清洗各機台與所有夾子", "23:10", 40),
        ("每日擦拭區域", "23:30", 50),
        ("一般垃圾打包", "23:40", 60),
        ("調店章、整理代收、找EC退貨、印EC標籤", "00:00", 70),
        ("先烤馬鈴薯2顆，再烤地瓜20至25顆分3輪", "01:00", 80),
        ("霜淇淋機殺菌清潔", "01:00", 90),
        ("店內外掃拖", "01:30", 100),
        ("熱狗機前後轉到4並預熱", "03:00", 110),
        ("蒸包機加水預熱", "03:00", 120),
        ("烤熱狗3包", "03:30", 130),
        ("烤包子10至15顆", "04:00", 140),
        ("補貨：OC牛奶、賣場、WI", "04:00", 150),
        ("大夜班進貨登錄", "04:00", 160),
        ("檢查退貨：雜誌、玩具、贈品", "04:30", 170),
        ("交班確認與短收登錄", "06:50", 180),
    ]
    count = db.execute("SELECT COUNT(*) c FROM work_template_items WHERE template_id=?", (night_id,)).fetchone()["c"]
    if count == 0:
        db.executemany(
            "INSERT INTO work_template_items(template_id,title,scheduled_time,sort_order) VALUES (?,?,?,?)",
            [(night_id, title, time, order) for title, time, order in night_items],
        )

    late_count = db.execute("SELECT COUNT(*) c FROM work_template_items WHERE template_id=?", (late_id,)).fetchone()["c"]
    if late_count == 0:
        db.executemany(
            "INSERT INTO work_template_items(template_id,title,scheduled_time,sort_order) VALUES (?,?,?,?)",
            [
                (late_id, "上班交接確認", "15:00", 10),
                (late_id, "補貨與賣場整理", "17:00", 20),
                (late_id, "清潔與交班紀錄", "22:30", 30),
                (late_id, "短收登錄", "22:50", 40),
            ],
        )

    defaults = [
        ("建昌晚班", "B", "15:00", "23:00", "#78cfa8", "🌆", late_id),
        ("建昌大夜", "B", "23:00", "07:00", "#7fa9e8", "🌙", night_id),
        ("溪洲晚班", "C", "15:00", "23:00", "#6fcbb8", "🌆", late_id),
        ("溪洲大夜", "C", "23:00", "07:00", "#ad8ee8", "🌙", night_id),
        ("休假", "X", "00:00", "00:00", "#c9ccd5", "🏖️", None),
    ]
    for row in defaults:
        db.execute(
            '''INSERT OR IGNORE INTO shift_types
               (name,store_code,start_time,end_time,color,icon,template_id)
               VALUES (?,?,?,?,?,?,?)''', row
        )

def upsert_user(line_user_id, display_name, picture_url):
    with connect() as db:
        db.execute(
            '''INSERT INTO users(line_user_id,display_name,picture_url)
               VALUES (?,?,?)
               ON CONFLICT(line_user_id) DO UPDATE SET
               display_name=excluded.display_name,picture_url=excluded.picture_url,
               last_login_at=CURRENT_TIMESTAMP''',
            (line_user_id, display_name, picture_url),
        )

def list_shift_types(active_only=False):
    sql = "SELECT * FROM shift_types"
    if active_only:
        sql += " WHERE is_active=1"
    sql += " ORDER BY id"
    with connect() as db:
        return [dict(r) for r in db.execute(sql).fetchall()]

def add_shift_type(name, store_code, start_time, end_time, color, icon, template_id=None):
    with connect() as db:
        db.execute(
            '''INSERT INTO shift_types(name,store_code,start_time,end_time,color,icon,template_id)
               VALUES (?,?,?,?,?,?,?)''',
            (name,store_code,start_time,end_time,color,icon,template_id or None),
        )

def list_shifts():
    with connect() as db:
        rows = db.execute(
            '''SELECT s.*, st.name shift_name, st.start_time, st.end_time, st.color, st.icon
               FROM shifts s LEFT JOIN shift_types st ON st.id=s.shift_type_id
               ORDER BY s.work_date DESC'''
        ).fetchall()
        return [dict(r) for r in rows]

def get_shift(work_date):
    with connect() as db:
        row = db.execute(
            '''SELECT s.*, st.name shift_name, st.start_time, st.end_time, st.color, st.icon, st.template_id
               FROM shifts s LEFT JOIN shift_types st ON st.id=s.shift_type_id
               WHERE s.work_date=?''', (work_date,)
        ).fetchone()
        return dict(row) if row else None

def get_today_shift(work_date):
    return get_shift(work_date)

def save_shift(work_date, shift_type_id, overtime=0, overtime_end=None, note=""):
    with connect() as db:
        st = db.execute("SELECT * FROM shift_types WHERE id=?", (shift_type_id,)).fetchone()
        if not st:
            raise ValueError("班別不存在")
        legacy_type = "off" if st["store_code"] == "X" else ("late" if st["start_time"] == "15:00" else "night")
        db.execute(
            '''INSERT INTO shifts(work_date,store_code,shift_type,shift_type_id,overtime,overtime_end,note)
               VALUES (?,?,?,?,?,?,?)
               ON CONFLICT(work_date) DO UPDATE SET
               store_code=excluded.store_code,shift_type=excluded.shift_type,
               shift_type_id=excluded.shift_type_id,overtime=excluded.overtime,
               overtime_end=excluded.overtime_end,note=excluded.note,
               updated_at=CURRENT_TIMESTAMP''',
            (work_date, st["store_code"], legacy_type, shift_type_id, int(bool(overtime)), overtime_end or None, note),
        )
        shift_id = db.execute("SELECT id FROM shifts WHERE work_date=?", (work_date,)).fetchone()["id"]
        db.execute("DELETE FROM daily_work_items WHERE work_date=? AND is_done=0", (work_date,))
        if st["template_id"]:
            items = db.execute(
                "SELECT * FROM work_template_items WHERE template_id=? ORDER BY sort_order,id",
                (st["template_id"],),
            ).fetchall()
            for item in items:
                db.execute(
                    '''INSERT OR IGNORE INTO daily_work_items
                       (work_date,shift_id,template_item_id,title,scheduled_time,category)
                       VALUES (?,?,?,?,?,?)''',
                    (work_date,shift_id,item["id"],item["title"],item["scheduled_time"],item["category"]),
                )

def delete_shift(work_date):
    with connect() as db:
        db.execute("DELETE FROM daily_work_items WHERE work_date=?", (work_date,))
        db.execute("DELETE FROM shifts WHERE work_date=?", (work_date,))

def list_templates():
    with connect() as db:
        rows = db.execute(
            '''SELECT t.*, COUNT(i.id) item_count
               FROM work_templates t LEFT JOIN work_template_items i ON i.template_id=t.id
               GROUP BY t.id ORDER BY t.id'''
        ).fetchall()
        return [dict(r) for r in rows]

def get_template(template_id):
    with connect() as db:
        t = db.execute("SELECT * FROM work_templates WHERE id=?", (template_id,)).fetchone()
        if not t:
            return None
        data = dict(t)
        data["items"] = [dict(r) for r in db.execute(
            "SELECT * FROM work_template_items WHERE template_id=? ORDER BY sort_order,id", (template_id,)
        ).fetchall()]
        return data

def add_template_item(template_id, title, scheduled_time="", category="work"):
    with connect() as db:
        max_order = db.execute(
            "SELECT COALESCE(MAX(sort_order),0)+10 n FROM work_template_items WHERE template_id=?",
            (template_id,),
        ).fetchone()["n"]
        db.execute(
            "INSERT INTO work_template_items(template_id,title,scheduled_time,category,sort_order) VALUES (?,?,?,?,?)",
            (template_id,title,scheduled_time or None,category,max_order),
        )

def delete_template_item(item_id):
    with connect() as db:
        db.execute("DELETE FROM work_template_items WHERE id=?", (item_id,))

def list_daily_work(work_date):
    with connect() as db:
        return [dict(r) for r in db.execute(
            "SELECT * FROM daily_work_items WHERE work_date=? ORDER BY scheduled_time,id", (work_date,)
        ).fetchall()]

def toggle_daily_work(item_id):
    with connect() as db:
        row = db.execute("SELECT is_done FROM daily_work_items WHERE id=?", (item_id,)).fetchone()
        if row:
            value = 0 if row["is_done"] else 1
            db.execute(
                "UPDATE daily_work_items SET is_done=?,completed_at=CASE WHEN ?=1 THEN CURRENT_TIMESTAMP ELSE NULL END WHERE id=?",
                (value,value,item_id),
            )

def attendance_for(work_date):
    with connect() as db:
        row = db.execute("SELECT * FROM attendance WHERE work_date=?", (work_date,)).fetchone()
        return dict(row) if row else None

def check_in(work_date, shift_id=None):
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with connect() as db:
        db.execute(
            '''INSERT INTO attendance(work_date,shift_id,check_in_at)
               VALUES (?,?,?)
               ON CONFLICT(work_date) DO UPDATE SET check_in_at=excluded.check_in_at,updated_at=CURRENT_TIMESTAMP''',
            (work_date,shift_id,now),
        )

def check_out(work_date):
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with connect() as db:
        db.execute(
            '''INSERT INTO attendance(work_date,check_out_at)
               VALUES (?,?)
               ON CONFLICT(work_date) DO UPDATE SET check_out_at=excluded.check_out_at,updated_at=CURRENT_TIMESTAMP''',
            (work_date,now),
        )

def inventory_for(work_date):
    with connect() as db:
        row = db.execute("SELECT * FROM inventory_logs WHERE work_date=?", (work_date,)).fetchone()
        return dict(row) if row else None

def inventory_arrive(work_date):
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with connect() as db:
        db.execute(
            '''INSERT INTO inventory_logs(work_date,arrived_at) VALUES (?,?)
               ON CONFLICT(work_date) DO UPDATE SET arrived_at=excluded.arrived_at,updated_at=CURRENT_TIMESTAMP''',
            (work_date,now),
        )

def inventory_complete(work_date):
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with connect() as db:
        db.execute(
            '''INSERT INTO inventory_logs(work_date,completed_at) VALUES (?,?)
               ON CONFLICT(work_date) DO UPDATE SET completed_at=excluded.completed_at,updated_at=CURRENT_TIMESTAMP''',
            (work_date,now),
        )

def add_work_log(work_date, store_code, category, title, content="", amount=0):
    with connect() as db:
        db.execute(
            "INSERT INTO work_logs(work_date,store_code,category,title,content,amount) VALUES (?,?,?,?,?,?)",
            (work_date,store_code,category,title,content,amount),
        )

def list_work_logs(limit=100):
    with connect() as db:
        return [dict(r) for r in db.execute(
            "SELECT * FROM work_logs ORDER BY work_date DESC,id DESC LIMIT ?", (limit,)
        ).fetchall()]

def delete_work_log(log_id):
    with connect() as db:
        db.execute("DELETE FROM work_logs WHERE id=?", (log_id,))

def add_task(title, due_date=None, note=""):
    with connect() as db:
        db.execute("INSERT INTO tasks(title,due_date,note) VALUES (?,?,?)",(title,due_date or None,note))

def list_tasks(show_done=True):
    sql = "SELECT * FROM tasks"
    if not show_done:
        sql += " WHERE is_done=0"
    sql += " ORDER BY is_done,COALESCE(due_date,'9999-12-31'),id DESC"
    with connect() as db:
        return [dict(r) for r in db.execute(sql).fetchall()]

def toggle_task(task_id):
    with connect() as db:
        row = db.execute("SELECT is_done FROM tasks WHERE id=?", (task_id,)).fetchone()
        if row:
            value = 0 if row["is_done"] else 1
            db.execute(
                "UPDATE tasks SET is_done=?,completed_at=CASE WHEN ?=1 THEN CURRENT_TIMESTAMP ELSE NULL END WHERE id=?",
                (value,value,task_id),
            )

def delete_task(task_id):
    with connect() as db:
        db.execute("DELETE FROM tasks WHERE id=?", (task_id,))

def dashboard_counts(work_date=None):
    work_date = work_date or datetime.now().strftime("%Y-%m-%d")
    with connect() as db:
        pending_tasks = db.execute("SELECT COUNT(*) c FROM tasks WHERE is_done=0").fetchone()["c"]
        work_total = db.execute("SELECT COUNT(*) c FROM daily_work_items WHERE work_date=?", (work_date,)).fetchone()["c"]
        work_done = db.execute("SELECT COUNT(*) c FROM daily_work_items WHERE work_date=? AND is_done=1",(work_date,)).fetchone()["c"]
        shortages = db.execute(
            "SELECT COALESCE(SUM(amount),0) total FROM work_logs WHERE category='shortage' AND work_date=?",
            (work_date,),
        ).fetchone()["total"]
    return {
        "pending_tasks": pending_tasks,
        "work_logs": work_total,
        "work_total": work_total,
        "work_done": work_done,
        "shortage_total": shortages,
    }


def add_reminder(title, reminder_type, remind_date, remind_time, related_url="/dashboard", note="", line_push=1, show_carousel=1):
    with connect() as db:
        db.execute(
            """INSERT INTO reminders
               (title,reminder_type,remind_date,remind_time,related_url,note,line_push,show_carousel)
               VALUES (?,?,?,?,?,?,?,?)""",
            (title, reminder_type, remind_date, remind_time, related_url, note, int(bool(line_push)), int(bool(show_carousel))),
        )

def list_reminders(include_done=True, limit=100):
    sql = "SELECT * FROM reminders"
    if not include_done:
        sql += " WHERE is_done=0"
    sql += " ORDER BY remind_date, remind_time, id LIMIT ?"
    with connect() as db:
        return [dict(r) for r in db.execute(sql, (limit,)).fetchall()]

def list_today_carousel_reminders(work_date):
    with connect() as db:
        return [dict(r) for r in db.execute(
            """SELECT * FROM reminders
               WHERE remind_date=? AND is_done=0 AND show_carousel=1
               ORDER BY remind_time,id""",
            (work_date,),
        ).fetchall()]

def due_reminders(now_date, now_time):
    with connect() as db:
        return [dict(r) for r in db.execute(
            """SELECT * FROM reminders
               WHERE is_done=0 AND sent_at IS NULL AND line_push=1
               AND (remind_date < ? OR (remind_date=? AND remind_time<=?))
               ORDER BY remind_date,remind_time,id""",
            (now_date, now_date, now_time),
        ).fetchall()]

def mark_reminder_sent(reminder_id):
    with connect() as db:
        db.execute("UPDATE reminders SET sent_at=CURRENT_TIMESTAMP WHERE id=?", (reminder_id,))

def complete_reminder(reminder_id):
    with connect() as db:
        db.execute("UPDATE reminders SET is_done=1 WHERE id=?", (reminder_id,))

def delete_reminder(reminder_id):
    with connect() as db:
        db.execute("DELETE FROM reminders WHERE id=?", (reminder_id,))

def add_notification_log(title, content="", notification_type="system", status="sent"):
    with connect() as db:
        db.execute(
            "INSERT INTO notification_logs(title,content,notification_type,status) VALUES (?,?,?,?)",
            (title, content, notification_type, status),
        )

def list_notification_logs(limit=100):
    with connect() as db:
        return [dict(r) for r in db.execute(
            "SELECT * FROM notification_logs ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()]

def upsert_health_record(record_date, steps=0, heart_rate=0, sleep_minutes=0, calories=0, water_ml=0, weight=0, note=""):
    with connect() as db:
        db.execute(
            """INSERT INTO health_records
               (record_date,steps,heart_rate,sleep_minutes,calories,water_ml,weight,note)
               VALUES (?,?,?,?,?,?,?,?)
               ON CONFLICT(record_date) DO UPDATE SET
               steps=excluded.steps,heart_rate=excluded.heart_rate,
               sleep_minutes=excluded.sleep_minutes,calories=excluded.calories,
               water_ml=excluded.water_ml,weight=excluded.weight,note=excluded.note,
               updated_at=CURRENT_TIMESTAMP""",
            (record_date, steps, heart_rate, sleep_minutes, calories, water_ml, weight, note),
        )

def get_health_record(record_date):
    with connect() as db:
        row = db.execute("SELECT * FROM health_records WHERE record_date=?", (record_date,)).fetchone()
        return dict(row) if row else None

def list_health_records(limit=30):
    with connect() as db:
        return [dict(r) for r in db.execute(
            "SELECT * FROM health_records ORDER BY record_date DESC LIMIT ?", (limit,)
        ).fetchall()]

def add_finance_record(record_date, record_type, category, title, amount, note=""):
    with connect() as db:
        db.execute(
            "INSERT INTO finance_records(record_date,record_type,category,title,amount,note) VALUES (?,?,?,?,?,?)",
            (record_date, record_type, category, title, amount, note),
        )

def delete_finance_record(record_id):
    with connect() as db:
        db.execute("DELETE FROM finance_records WHERE id=?", (record_id,))

def list_finance_records(limit=100):
    with connect() as db:
        return [dict(r) for r in db.execute(
            "SELECT * FROM finance_records ORDER BY record_date DESC,id DESC LIMIT ?", (limit,)
        ).fetchall()]

def finance_summary(month_prefix):
    with connect() as db:
        row = db.execute(
            """SELECT
               COALESCE(SUM(CASE WHEN record_type='income' THEN amount ELSE 0 END),0) income,
               COALESCE(SUM(CASE WHEN record_type='expense' THEN amount ELSE 0 END),0) expense
               FROM finance_records WHERE record_date LIKE ?""",
            (month_prefix + "%",),
        ).fetchone()
        return dict(row)

def upsert_card(card_type, label, barcode_value, note=""):
    with connect() as db:
        db.execute(
            """INSERT INTO personal_cards(card_type,label,barcode_value,note)
               VALUES (?,?,?,?)
               ON CONFLICT(card_type) DO UPDATE SET
               label=excluded.label,barcode_value=excluded.barcode_value,
               note=excluded.note,updated_at=CURRENT_TIMESTAMP""",
            (card_type, label, barcode_value, note),
        )

def list_cards():
    with connect() as db:
        return [dict(r) for r in db.execute("SELECT * FROM personal_cards ORDER BY id").fetchall()]

def set_app_setting(key, value):
    with connect() as db:
        db.execute(
            """INSERT INTO app_settings(setting_key,setting_value) VALUES (?,?)
               ON CONFLICT(setting_key) DO UPDATE SET
               setting_value=excluded.setting_value,updated_at=CURRENT_TIMESTAMP""",
            (key, value),
        )

def get_app_setting(key, default=""):
    with connect() as db:
        row = db.execute("SELECT setting_value FROM app_settings WHERE setting_key=?", (key,)).fetchone()
        return row["setting_value"] if row else default
