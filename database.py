from pathlib import Path
from datetime import datetime, timedelta
import os
import re
import sqlite3

BASE_DIR = Path(__file__).resolve().parent
DATABASE_URL = (os.getenv("DATABASE_URL") or os.getenv("POSTGRES_URL") or "").strip()
DB_SCHEMA = (os.getenv("WORK_LIFE_DB_SCHEMA") or "worklife").strip()
if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", DB_SCHEMA):
    raise RuntimeError("WORK_LIFE_DB_SCHEMA 只能使用英文字母、數字與底線")


def _is_render() -> bool:
    return bool(os.getenv("RENDER") or os.getenv("RENDER_SERVICE_ID") or os.getenv("RENDER_EXTERNAL_URL"))


def _db_path() -> Path:
    custom = os.getenv("WORK_LIFE_DB_PATH", "").strip()
    if custom:
        return Path(custom).expanduser().resolve()
    if _is_render():
        return Path("/tmp/worklife.db")
    return (BASE_DIR / "data" / "worklife.db").resolve()


DB_PATH = _db_path()


def _prepare_database_path() -> None:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    if not os.access(DB_PATH.parent, os.W_OK):
        raise RuntimeError(f"資料庫目錄無法寫入：{DB_PATH.parent}")


class _PgCursor:
    def __init__(self, cursor):
        self._cursor = cursor

    @property
    def rowcount(self):
        return self._cursor.rowcount

    @property
    def lastrowid(self):
        row = self._cursor.fetchone()
        return row["id"] if row else None

    def fetchone(self):
        return self._cursor.fetchone()

    def fetchall(self):
        return self._cursor.fetchall()

    def __iter__(self):
        return iter(self._cursor)


class _PgConnection:
    def __init__(self, connection):
        self._connection = connection

    @staticmethod
    def _sql(sql: str) -> str:
        statement = sql.strip()
        statement = statement.replace("INTEGER PRIMARY KEY AUTOINCREMENT", "BIGSERIAL PRIMARY KEY")
        statement = statement.replace("?", "%s")
        if re.match(r"(?is)^INSERT\s+OR\s+IGNORE\s+INTO\s+", statement):
            statement = re.sub(r"(?is)^INSERT\s+OR\s+IGNORE\s+INTO\s+", "INSERT INTO ", statement)
            statement = statement.rstrip().rstrip(";") + " ON CONFLICT DO NOTHING"
        return statement

    def execute(self, sql, params=()):
        from psycopg2.extras import RealDictCursor
        cur = self._connection.cursor(cursor_factory=RealDictCursor)
        cur.execute(self._sql(sql), params or ())
        return _PgCursor(cur)

    def executemany(self, sql, seq):
        from psycopg2.extras import RealDictCursor
        cur = self._connection.cursor(cursor_factory=RealDictCursor)
        cur.executemany(self._sql(sql), seq)
        return _PgCursor(cur)

    def executescript(self, script):
        for statement in script.split(";"):
            if statement.strip():
                self.execute(statement)

    def commit(self):
        self._connection.commit()

    def rollback(self):
        self._connection.rollback()

    def close(self):
        self._connection.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        if exc_type is None:
            self._connection.commit()
        else:
            self._connection.rollback()
        self._connection.close()
        return False


def database_status() -> dict:
    if DATABASE_URL:
        return {
            "path": f"PostgreSQL / schema={DB_SCHEMA}",
            "exists": True,
            "size": 0,
            "persistent": True,
            "backend": "postgresql",
            "schema": DB_SCHEMA,
        }
    _prepare_database_path()
    return {
        "path": str(DB_PATH),
        "exists": DB_PATH.exists(),
        "size": DB_PATH.stat().st_size if DB_PATH.exists() else 0,
        "persistent": (not _is_render()) or str(DB_PATH).startswith("/var/data/"),
        "backend": "sqlite",
    }



def database_health_check() -> dict:
    """執行一次極輕量連線與主要資料表檢查；僅供 /healthz 呼叫。"""
    required_tables = (
        "shifts", "daily_work_items", "daily_logistics", "reminders",
        "activities", "tasks", "notification_logs", "app_settings",
        "maintenance_logs",
    )
    started = datetime.now()
    try:
        with connect() as db:
            db.execute("SELECT 1").fetchone()
            missing = []
            for table in required_tables:
                try:
                    db.execute(f'SELECT 1 FROM "{table}" LIMIT 1').fetchone()
                except Exception:
                    missing.append(table)
        elapsed_ms = max(0, int((datetime.now() - started).total_seconds() * 1000))
        return {
            "ok": not missing,
            "connected": True,
            "missing_tables": missing,
            "checked_tables": len(required_tables),
            "latency_ms": elapsed_ms,
            "error": "" if not missing else "缺少主要資料表",
        }
    except Exception as exc:
        elapsed_ms = max(0, int((datetime.now() - started).total_seconds() * 1000))
        return {
            "ok": False,
            "connected": False,
            "missing_tables": [],
            "checked_tables": 0,
            "latency_ms": elapsed_ms,
            "error": f"{type(exc).__name__}: {exc}",
        }

def connect():
    """有 DATABASE_URL 時使用共用 PostgreSQL 的 worklife schema；否則保留 SQLite 備援。"""
    if DATABASE_URL:
        try:
            import psycopg2
        except ImportError as exc:
            raise RuntimeError("缺少 psycopg2-binary，請更新 requirements.txt 後重新部署") from exc
        conn = psycopg2.connect(DATABASE_URL, connect_timeout=15, sslmode=os.getenv("PGSSLMODE", "prefer"))
        conn.autocommit = True
        with conn.cursor() as cur:
            cur.execute(f'CREATE SCHEMA IF NOT EXISTS "{DB_SCHEMA}"')
            cur.execute(f'SET search_path TO "{DB_SCHEMA}", public')
        conn.autocommit = False
        return _PgConnection(conn)

    _prepare_database_path()
    db = sqlite3.connect(str(DB_PATH), timeout=30)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys=ON")
    db.execute("PRAGMA busy_timeout=30000")
    db.execute("PRAGMA journal_mode=WAL")
    db.execute("PRAGMA synchronous=FULL")
    return db

def _columns(db, table):
    if DATABASE_URL:
        return {r["column_name"] for r in db.execute(
            "SELECT column_name FROM information_schema.columns WHERE table_schema=? AND table_name=?",
            (DB_SCHEMA, table),
        )}
    return {r["name"] for r in db.execute(f"PRAGMA table_info({table})")}

def _add_column(db, table, definition):
    name = definition.split()[0]
    if name not in _columns(db, table):
        db.execute(f"ALTER TABLE {table} ADD COLUMN {definition}")

def init_db():
    with connect() as db:
        db.executescript("""
        CREATE TABLE IF NOT EXISTS schema_migrations(
            migration_key TEXT PRIMARY KEY,
            applied_at TEXT DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS users(
            line_user_id TEXT PRIMARY KEY,
            display_name TEXT NOT NULL,
            picture_url TEXT,
            created_at TEXT,
            last_login_at TEXT
        );
        CREATE TABLE IF NOT EXISTS work_templates(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT UNIQUE NOT NULL,
            description TEXT DEFAULT '',
            created_at TEXT,
            updated_at TEXT
        );
        CREATE TABLE IF NOT EXISTS work_template_items(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            template_id INTEGER NOT NULL,
            title TEXT NOT NULL,
            scheduled_time TEXT,
            icon TEXT DEFAULT '✅',
            category TEXT DEFAULT '工作',
            sort_order INTEGER DEFAULT 0,
            condition_type TEXT DEFAULT 'always',
            FOREIGN KEY(template_id) REFERENCES work_templates(id) ON DELETE CASCADE
        );
        CREATE TABLE IF NOT EXISTS shift_types(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT UNIQUE NOT NULL,
            store_code TEXT NOT NULL,
            start_time TEXT NOT NULL,
            end_time TEXT NOT NULL,
            icon TEXT DEFAULT '🌙',
            color TEXT DEFAULT '#8f7aea',
            template_id INTEGER,
            is_active INTEGER DEFAULT 1
        );
        CREATE TABLE IF NOT EXISTS shifts(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            work_date TEXT UNIQUE NOT NULL,
            shift_type_id INTEGER NOT NULL,
            overtime INTEGER DEFAULT 0,
            overtime_end TEXT,
            manager_tasks INTEGER DEFAULT 0,
            note TEXT DEFAULT '',
            created_at TEXT,
            updated_at TEXT,
            FOREIGN KEY(shift_type_id) REFERENCES shift_types(id)
        );
        CREATE TABLE IF NOT EXISTS daily_work_items(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            work_date TEXT NOT NULL,
            shift_id INTEGER,
            template_item_id INTEGER,
            title TEXT NOT NULL,
            scheduled_time TEXT,
            icon TEXT DEFAULT '✅',
            category TEXT DEFAULT '工作',
            is_done INTEGER DEFAULT 0,
            completed_at TEXT,
            created_at TEXT,
            UNIQUE(work_date,template_item_id)
        );
        CREATE TABLE IF NOT EXISTS logistics_settings(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT UNIQUE NOT NULL,
            icon TEXT DEFAULT '🚚',
            start_time TEXT NOT NULL,
            end_time TEXT NOT NULL,
            content TEXT DEFAULT '',
            applies_b INTEGER DEFAULT 1,
            applies_c INTEGER DEFAULT 1,
            applies_late INTEGER DEFAULT 0,
            applies_night INTEGER DEFAULT 0,
            remind_minutes INTEGER DEFAULT 10,
            line_push INTEGER DEFAULT 1,
            show_carousel INTEGER DEFAULT 1,
            is_active INTEGER DEFAULT 1,
            updated_at TEXT
        );
        CREATE TABLE IF NOT EXISTS daily_logistics(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            work_date TEXT NOT NULL,
            logistics_id INTEGER NOT NULL,
            arrived_at TEXT,
            completed_at TEXT,
            created_at TEXT,
            UNIQUE(work_date,logistics_id),
            FOREIGN KEY(logistics_id) REFERENCES logistics_settings(id) ON DELETE CASCADE
        );
        CREATE TABLE IF NOT EXISTS reminders(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            reminder_type TEXT DEFAULT '自訂',
            remind_date TEXT NOT NULL,
            remind_time TEXT NOT NULL,
            note TEXT DEFAULT '',
            related_url TEXT DEFAULT '/dashboard',
            line_push INTEGER DEFAULT 1,
            show_carousel INTEGER DEFAULT 1,
            sent_at TEXT,
            is_done INTEGER DEFAULT 0,
            created_at TEXT
        );
        CREATE TABLE IF NOT EXISTS activities(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            activity_date TEXT NOT NULL,
            activity_time TEXT DEFAULT '',
            location TEXT DEFAULT '',
            note TEXT DEFAULT '',
            line_push INTEGER DEFAULT 1,
            remind_minutes INTEGER DEFAULT 30,
            is_done INTEGER DEFAULT 0,
            created_at TEXT,
            updated_at TEXT,
            reminded_at TEXT
        );
        CREATE TABLE IF NOT EXISTS notification_logs(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            content TEXT DEFAULT '',
            notification_type TEXT DEFAULT '系統',
            status TEXT DEFAULT '已推播',
            sent_at TEXT
        );
        CREATE TABLE IF NOT EXISTS attendance(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            work_date TEXT UNIQUE NOT NULL,
            shift_id INTEGER,
            check_in_at TEXT,
            check_out_at TEXT,
            updated_at TEXT
        );
        CREATE TABLE IF NOT EXISTS tasks(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            due_date TEXT,
            note TEXT DEFAULT '',
            is_done INTEGER DEFAULT 0,
            created_at TEXT,
            completed_at TEXT
        );
        CREATE TABLE IF NOT EXISTS work_logs(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            work_date TEXT NOT NULL,
            category TEXT NOT NULL,
            title TEXT NOT NULL,
            amount INTEGER DEFAULT 0,
            note TEXT DEFAULT '',
            created_at TEXT
        );
        CREATE TABLE IF NOT EXISTS app_settings(
            setting_key TEXT PRIMARY KEY,
            setting_value TEXT DEFAULT '',
            updated_at TEXT
        );
        CREATE TABLE IF NOT EXISTS maintenance_logs(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_date TEXT NOT NULL,
            started_at TEXT NOT NULL,
            finished_at TEXT NOT NULL,
            duration_ms INTEGER DEFAULT 0,
            shift_cutoff TEXT DEFAULT '',
            shifts_deleted INTEGER DEFAULT 0,
            work_items_deleted INTEGER DEFAULT 0,
            logistics_deleted INTEGER DEFAULT 0,
            attendance_deleted INTEGER DEFAULT 0,
            tasks_deleted INTEGER DEFAULT 0,
            reminders_deleted INTEGER DEFAULT 0,
            activities_deleted INTEGER DEFAULT 0,
            notification_logs_deleted INTEGER DEFAULT 0,
            status TEXT DEFAULT '完成',
            error_message TEXT DEFAULT ''
        );
        """)
        # 舊版本資料庫完整相容升級。覆蓋部署時不刪除既有資料。
        migrations = {
            "users": ["picture_url TEXT", "created_at TEXT", "last_login_at TEXT"],
            "work_templates": ["description TEXT DEFAULT ''", "created_at TEXT", "updated_at TEXT"],
            "work_template_items": ["scheduled_time TEXT", "icon TEXT DEFAULT '✅'", "category TEXT DEFAULT '工作'", "sort_order INTEGER DEFAULT 0", "condition_type TEXT DEFAULT 'always'"],
            "shift_types": ["store_code TEXT DEFAULT 'B'", "start_time TEXT DEFAULT '00:00'", "end_time TEXT DEFAULT '00:00'", "icon TEXT DEFAULT '🌙'", "color TEXT DEFAULT '#8f7aea'", "template_id INTEGER", "is_active INTEGER DEFAULT 1"],
            "shifts": ["overtime INTEGER DEFAULT 0", "overtime_end TEXT", "manager_tasks INTEGER DEFAULT 0", "note TEXT DEFAULT ''", "created_at TEXT", "updated_at TEXT"],
            "daily_work_items": ["shift_id INTEGER", "template_item_id INTEGER", "scheduled_time TEXT", "icon TEXT DEFAULT '✅'", "category TEXT DEFAULT '工作'", "is_done INTEGER DEFAULT 0", "completed_at TEXT", "created_at TEXT"],
            "logistics_settings": ["icon TEXT DEFAULT '🚚'", "start_time TEXT DEFAULT '00:00'", "end_time TEXT DEFAULT '00:00'", "content TEXT DEFAULT ''", "applies_b INTEGER DEFAULT 1", "applies_c INTEGER DEFAULT 1", "applies_late INTEGER DEFAULT 0", "applies_night INTEGER DEFAULT 0", "remind_minutes INTEGER DEFAULT 10", "line_push INTEGER DEFAULT 1", "show_carousel INTEGER DEFAULT 1", "is_active INTEGER DEFAULT 1", "updated_at TEXT"],
            "daily_logistics": ["shift_id INTEGER", "logistics_id INTEGER", "arrived_at TEXT", "completed_at TEXT", "reminded_at TEXT", "created_at TEXT"],
            "reminders": ["reminder_type TEXT DEFAULT '自訂'", "note TEXT DEFAULT ''", "related_url TEXT DEFAULT '/dashboard'", "line_push INTEGER DEFAULT 1", "show_carousel INTEGER DEFAULT 1", "sent_at TEXT", "is_done INTEGER DEFAULT 0", "created_at TEXT"],
            "activities": ["activity_time TEXT DEFAULT ''", "location TEXT DEFAULT ''", "note TEXT DEFAULT ''", "line_push INTEGER DEFAULT 1", "remind_minutes INTEGER DEFAULT 30", "is_done INTEGER DEFAULT 0", "created_at TEXT", "updated_at TEXT", "reminded_at TEXT"],
            "notification_logs": ["content TEXT DEFAULT ''", "notification_type TEXT DEFAULT '系統'", "status TEXT DEFAULT '已推播'", "sent_at TEXT"],
            "attendance": ["shift_id INTEGER", "check_in_at TEXT", "check_out_at TEXT", "updated_at TEXT"],
            "tasks": ["due_date TEXT", "note TEXT DEFAULT ''", "is_done INTEGER DEFAULT 0", "created_at TEXT", "completed_at TEXT"],
            "work_logs": ["amount INTEGER DEFAULT 0", "note TEXT DEFAULT ''", "created_at TEXT"],
            "app_settings": ["setting_value TEXT DEFAULT ''", "updated_at TEXT"],
            "maintenance_logs": ["run_date TEXT", "started_at TEXT", "finished_at TEXT", "duration_ms INTEGER DEFAULT 0", "shift_cutoff TEXT DEFAULT ''", "shifts_deleted INTEGER DEFAULT 0", "work_items_deleted INTEGER DEFAULT 0", "logistics_deleted INTEGER DEFAULT 0", "attendance_deleted INTEGER DEFAULT 0", "tasks_deleted INTEGER DEFAULT 0", "reminders_deleted INTEGER DEFAULT 0", "activities_deleted INTEGER DEFAULT 0", "notification_logs_deleted INTEGER DEFAULT 0", "status TEXT DEFAULT '完成'", "error_message TEXT DEFAULT ''"],
        }
        for table, definitions in migrations.items():
            for definition in definitions:
                _add_column(db, table, definition)
        _apply_default_migration(db)
        _apply_phase2_migration(db)
        _apply_performance_indexes(db)


def _apply_performance_indexes(db):
    """建立排程與首頁常用索引；可重複執行，不改動既有資料。"""
    statements = [
        "CREATE INDEX IF NOT EXISTS idx_shifts_work_date ON shifts(work_date)",
        "CREATE INDEX IF NOT EXISTS idx_daily_work_date_done ON daily_work_items(work_date,is_done)",
        "CREATE INDEX IF NOT EXISTS idx_daily_logistics_date ON daily_logistics(work_date)",
        "CREATE INDEX IF NOT EXISTS idx_reminders_due ON reminders(remind_date,remind_time,is_done,sent_at,line_push)",
        "CREATE INDEX IF NOT EXISTS idx_activities_due ON activities(activity_date,is_done,reminded_at,line_push)",
        "CREATE INDEX IF NOT EXISTS idx_tasks_pending ON tasks(is_done,due_date)",
        "CREATE INDEX IF NOT EXISTS idx_notification_logs_sent ON notification_logs(sent_at)",
        "CREATE INDEX IF NOT EXISTS idx_work_logs_date ON work_logs(work_date)",
        "CREATE INDEX IF NOT EXISTS idx_maintenance_logs_run_date ON maintenance_logs(run_date,started_at)",
    ]
    for sql in statements:
        db.execute(sql)


def _first_day_previous_month(day):
    first = day.replace(day=1)
    return (first - timedelta(days=1)).replace(day=1)


def latest_maintenance_log():
    """回傳最近一次每日維護摘要；沒有紀錄時回傳 None。"""
    with connect() as db:
        row = db.execute("SELECT * FROM maintenance_logs ORDER BY started_at DESC,id DESC LIMIT 1").fetchone()
        return dict(row) if row else None


def run_daily_maintenance(today=None):
    """每天 04:00 執行一次的低負載維護，並只保留最近 10 次摘要。"""
    import time
    today = today or datetime.now().date()
    started = datetime.now()
    started_clock = time.monotonic()

    task_cutoff = (today - timedelta(days=60)).isoformat()
    activity_cutoff = (today - timedelta(days=180)).isoformat()
    log_cutoff = (today - timedelta(days=30)).isoformat()
    result = {
        "run_date": today.isoformat(),
        "started_at": started.strftime("%Y-%m-%d %H:%M:%S"),
        "shift_cutoff": "",
        "shifts_deleted": 0,
        "work_items_deleted": 0,
        "logistics_deleted": 0,
        "attendance_deleted": 0,
        "tasks_deleted": 0,
        "reminders_deleted": 0,
        "activities_deleted": 0,
        "notification_logs_deleted": 0,
        "shift_markers_deleted": 0,
        "status": "完成",
        "error_message": "",
    }

    try:
        with connect() as db:
            # 以班表資料中最新月份為基準，只保留最新兩個月份。
            latest = db.execute("SELECT MAX(work_date) AS latest_work_date FROM shifts").fetchone()
            latest_date_text = latest["latest_work_date"] if latest else None
            if latest_date_text:
                latest_day = datetime.strptime(str(latest_date_text)[:10], "%Y-%m-%d").date()
                shift_cutoff = _first_day_previous_month(latest_day).isoformat()
                result["shift_cutoff"] = shift_cutoff

                # 先清除由舊班表產生的附屬資料，再刪除舊班表。
                result["work_items_deleted"] = db.execute(
                    "DELETE FROM daily_work_items WHERE work_date<?", (shift_cutoff,)
                ).rowcount
                result["logistics_deleted"] = db.execute(
                    "DELETE FROM daily_logistics WHERE work_date<?", (shift_cutoff,)
                ).rowcount
                result["attendance_deleted"] = db.execute(
                    "DELETE FROM attendance WHERE work_date<?", (shift_cutoff,)
                ).rowcount
                result["shifts_deleted"] = db.execute(
                    "DELETE FROM shifts WHERE work_date<?", (shift_cutoff,)
                ).rowcount

                # 班表通知防重複標記會隨月份累積；同步清除已淘汰班表的舊標記。
                # setting_key 格式：shift_push_sent:YYYY-MM-DD:HH:MM
                result["shift_markers_deleted"] = db.execute(
                    """DELETE FROM app_settings
                       WHERE setting_key LIKE 'shift_push_sent:%'
                       AND substr(setting_key,17,10)<?""",
                    (shift_cutoff,),
                ).rowcount

            # 未完成事項永久保留；只有已完成且超過 60 天才清除。
            result["tasks_deleted"] = db.execute(
                """DELETE FROM tasks
                   WHERE is_done=1
                   AND COALESCE(substr(completed_at,1,10),due_date,substr(created_at,1,10),'9999-12-31')<?""",
                (task_cutoff,),
            ).rowcount
            result["reminders_deleted"] = db.execute(
                "DELETE FROM reminders WHERE is_done=1 AND remind_date<?", (task_cutoff,)
            ).rowcount

            # 未完成活動永久保留。
            result["activities_deleted"] = db.execute(
                "DELETE FROM activities WHERE is_done=1 AND activity_date<?", (activity_cutoff,)
            ).rowcount

            # LINE 推播紀錄只保留最近 30 天。
            result["notification_logs_deleted"] = db.execute(
                "DELETE FROM notification_logs WHERE sent_at IS NOT NULL AND substr(sent_at,1,10)<?",
                (log_cutoff,),
            ).rowcount

            if not DATABASE_URL:
                # SQLite 只做輕量最佳化，不執行耗時 VACUUM。
                db.execute("PRAGMA optimize")

            result["finished_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            result["duration_ms"] = max(0, int((time.monotonic() - started_clock) * 1000))
            db.execute(
                """INSERT INTO maintenance_logs(
                    run_date,started_at,finished_at,duration_ms,shift_cutoff,
                    shifts_deleted,work_items_deleted,logistics_deleted,attendance_deleted,
                    tasks_deleted,reminders_deleted,activities_deleted,notification_logs_deleted,status,error_message
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    result["run_date"],result["started_at"],result["finished_at"],result["duration_ms"],result["shift_cutoff"],
                    result["shifts_deleted"],result["work_items_deleted"],result["logistics_deleted"],result["attendance_deleted"],
                    result["tasks_deleted"],result["reminders_deleted"],result["activities_deleted"],result["notification_logs_deleted"],
                    result["status"],result["error_message"],
                ),
            )
            db.execute(
                "DELETE FROM maintenance_logs WHERE id NOT IN (SELECT id FROM maintenance_logs ORDER BY started_at DESC,id DESC LIMIT 10)"
            )
        return result
    except Exception as exc:
        result["status"] = "失敗"
        result["error_message"] = f"{type(exc).__name__}: {exc}"
        result["finished_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        result["duration_ms"] = max(0, int((time.monotonic() - started_clock) * 1000))
        try:
            with connect() as db:
                db.execute(
                    """INSERT INTO maintenance_logs(
                        run_date,started_at,finished_at,duration_ms,shift_cutoff,status,error_message
                    ) VALUES (?,?,?,?,?,?,?)""",
                    (result["run_date"],result["started_at"],result["finished_at"],result["duration_ms"],result["shift_cutoff"],result["status"],result["error_message"]),
                )
                db.execute(
                    "DELETE FROM maintenance_logs WHERE id NOT IN (SELECT id FROM maintenance_logs ORDER BY started_at DESC,id DESC LIMIT 10)"
                )
        except Exception:
            pass
        raise

def _template_id(db, name, description):
    db.execute("INSERT OR IGNORE INTO work_templates(name,description) VALUES (?,?)", (name,description))
    return db.execute("SELECT id FROM work_templates WHERE name=?", (name,)).fetchone()["id"]

def _replace_items(db, template_id, items):
    db.execute("DELETE FROM work_template_items WHERE template_id=?", (template_id,))
    db.executemany(
        """INSERT INTO work_template_items
        (template_id,title,scheduled_time,icon,category,sort_order,condition_type)
        VALUES (?,?,?,?,?,?,?)""",
        [(template_id,*item) for item in items]
    )

def _apply_default_migration(db):
    migration = "第二大包_工作物流_202607"
    exists = db.execute("SELECT 1 FROM schema_migrations WHERE migration_key=?", (migration,)).fetchone()
    if exists:
        return

    late = [
        ("訂購傳輸","21:30","📡","店務",10,"always"),
        ("收廢棄","22:00","🗑️","廢棄",20,"always"),
        ("關燈","22:00","💡","關店",30,"always"),
        ("關冷氣","22:00","❄️","關店",40,"always"),
        ("找零金兌換完畢","22:30","💰","金流",50,"always"),
    ]
    jiancang_night = [
        ("列管、找零金3000對點","23:00","💰","金流",10,"always"),
        ("寫品保","23:00","📝","品保",20,"always"),
        ("廢棄FF鮮食：地瓜、熱狗、包子、馬鈴薯","23:00","🗑️","廢棄",30,"always"),
        ("清洗地瓜機、熱狗機、蒸包機、膠囊茶機及所有夾子","23:10","🧼","清潔",40,"always"),
        ("每日擦拭各區域與設備外觀","23:30","✨","清潔",50,"always"),
        ("一般垃圾打包","23:40","♻️","清潔",60,"always"),
        ("調店章、整理代收、找EC退貨、列印EC標籤","00:00","🏷️","店務",70,"always"),
        ("清洗咖啡機，需在02:50前完成","01:00","☕","重要",80,"always"),
        ("店內外掃拖","01:30","🧹","清潔",90,"always"),
        ("熱狗機轉到4預熱","03:00","🌭","熟食",100,"always"),
        ("蒸包機加水預熱","03:00","🥟","熟食",110,"always"),
        ("烤地瓜20至25顆","03:00","🍠","熟食",120,"always"),
        ("烤熱狗2包：原味1、起司1","03:30","🌭","熟食",130,"always"),
        ("烤包子約10顆","04:00","🥟","熟食",140,"always"),
        ("補貨：OC牛奶、賣場、WI","04:00","📦","補貨",150,"always"),
        ("檢查雜誌、玩具、贈品退貨；一番賞需告知店長","04:30","↩️","退貨",160,"wed_sun"),
        ("咖啡機大清：消毒粉包、拆豆槽","01:00","☕","店長交辦",170,"manager"),
        ("自助區大清：移開機台擦拭桌面","01:30","🧽","店長交辦",180,"manager"),
        ("熱狗機兩側滾輪清潔","02:00","🌭","店長交辦",190,"manager"),
        ("所有防塵蓋清洗","02:10","🧼","店長交辦",200,"manager"),
        ("熱狗備品盒擦拭","02:20","📦","店長交辦",210,"manager"),
        ("冷氣濾網清洗","02:30","❄️","店長交辦",220,"manager"),
    ]
    xizhou_night = [
        ("列管、找零金3000對點","23:00","💰","金流",10,"always"),
        ("寫品保","23:00","📝","品保",20,"always"),
        ("廢棄FF鮮食：地瓜、熱狗、包子、馬鈴薯、蒸玉米","23:00","🗑️","廢棄",30,"always"),
        ("清洗咖啡機、地瓜機、熱狗機、蒸包機、膠囊茶機、蒸玉米機及所有夾子","23:10","🧼","清潔",40,"always"),
        ("每日擦拭各區域與設備外觀","23:30","✨","清潔",50,"always"),
        ("一般垃圾打包","23:40","♻️","清潔",60,"always"),
        ("調店章、整理代收、找EC退貨、列印EC標籤","00:00","🏷️","店務",70,"always"),
        ("烤馬鈴薯2顆、烤地瓜20至25顆分3輪","01:00","🍠","熟食",80,"always"),
        ("霜淇淋機殺菌清潔","01:00","🍦","重要",90,"always"),
        ("店內外掃拖","01:30","🧹","清潔",100,"always"),
        ("熱狗機轉到4預熱","03:00","🌭","熟食",110,"always"),
        ("蒸包機加水預熱","03:00","🥟","熟食",120,"always"),
        ("蒸箱加水","03:00","🌽","熟食",130,"always"),
        ("烤熱狗3包","03:30","🌭","熟食",140,"always"),
        ("烤包子約10至15顆","04:00","🥟","熟食",150,"always"),
        ("放玉米下去蒸","04:00","🌽","熟食",160,"always"),
        ("補貨：OC牛奶、賣場、WI","04:00","📦","補貨",170,"always"),
        ("檢查雜誌、玩具、贈品退貨；一番賞需告知店長","04:30","↩️","退貨",180,"wed_sun"),
        ("咖啡機大清：消毒粉包、拆豆槽","01:00","☕","大清",190,"sunday"),
        ("自助區大清：移開機台擦拭桌面","01:30","🧽","大清",200,"sunday"),
        ("熱狗機兩側滾輪清潔","02:00","🌭","大清",210,"sunday"),
        ("所有防塵蓋清洗","02:10","🧼","大清",220,"sunday"),
        ("熱狗備品盒擦拭","02:20","📦","大清",230,"sunday"),
        ("冷氣濾網清洗","02:30","❄️","大清",240,"sunday"),
    ]

    late_id = _template_id(db,"晚班工作範本","建昌與溪洲晚班共用")
    jn_id = _template_id(db,"建昌大夜班工作範本","建昌大夜班")
    xn_id = _template_id(db,"溪洲大夜班工作範本","溪洲大夜班")
    _replace_items(db,late_id,late)
    _replace_items(db,jn_id,jiancang_night)
    _replace_items(db,xn_id,xizhou_night)

    shift_defaults = [
        ("建昌晚班","B","15:00","23:00","🌆","#78cfa8",late_id),
        ("建昌大夜","B","23:00","07:00","🌙","#7fa9e8",jn_id),
        ("溪洲晚班","C","15:00","23:00","🌆","#6fcbb8",late_id),
        ("溪洲大夜","C","23:00","07:00","🌙","#ad8ee8",xn_id),
        ("休假","X","00:00","00:00","🏖️","#c9ccd5",None),
    ]
    for row in shift_defaults:
        db.execute(
            """INSERT INTO shift_types(name,store_code,start_time,end_time,icon,color,template_id)
            VALUES (?,?,?,?,?,?,?)
            ON CONFLICT(name) DO UPDATE SET
            store_code=excluded.store_code,start_time=excluded.start_time,end_time=excluded.end_time,
            icon=excluded.icon,color=excluded.color,template_id=excluded.template_id""", row
        )

    logistics = [
        ("日翊","📦","03:40","07:10","包裹、EC包裹、宅配包裹、包裹整理",0,1),
        ("低溫一配","🥶","03:50","05:20","便當、微波食品、冷藏鮮食",0,1),
        ("鮮一","🍞","03:50","05:20","麵包、飯糰、三明治、早餐商品",0,1),
        ("巧克力","🍫","03:50","05:20","巧克力、糖果、零食",0,1),
        ("常溫","📦","06:20","09:50","飲料、常溫食品、日用品、雜貨",0,1),
        ("低溫二配","🥶","12:20","13:50","第二批便當、微波食品、冷藏鮮食",1,0),
        ("鮮二","🍞","12:20","13:50","第二批麵包、飯糰、三明治",1,0),
        ("冷凍","🧊","15:20","18:50","冷凍食品、冰品、冷凍補貨",1,0),
    ]
    for name,icon,start,end,content,late,night in logistics:
        db.execute(
            """INSERT INTO logistics_settings
            (name,icon,start_time,end_time,content,applies_late,applies_night)
            VALUES (?,?,?,?,?,?,?)
            ON CONFLICT(name) DO UPDATE SET
            icon=excluded.icon,start_time=excluded.start_time,end_time=excluded.end_time,
            content=excluded.content,applies_late=excluded.applies_late,
            applies_night=excluded.applies_night""",
            (name,icon,start,end,content,late,night)
        )

    db.execute("INSERT INTO schema_migrations(migration_key) VALUES (?)",(migration,))


def _apply_phase2_migration(db):
    """Phase 2：套用店舖工作流程與物流提醒，不刪除已完成紀錄。"""
    migration = "Phase2_工作流程物流提醒_20260718"
    if db.execute("SELECT 1 FROM schema_migrations WHERE migration_key=?", (migration,)).fetchone():
        return

    # 溪洲大夜依照目前實際作業時間重新整理。
    xizhou_night = [
        ("接班", "23:00", "🤝", "交班", 10, "always"),
        ("清潔", "00:00", "🧼", "清潔", 20, "always"),
        ("關東煮整理", "01:00", "🍢", "熟食", 30, "always"),
        ("店內外掃拖", "01:30", "🧹", "清潔", 40, "always"),
        ("蒸箱加水", "03:00", "🌽", "熟食", 50, "always"),
        ("日翊進貨：包裹", "03:40", "📦", "物流", 60, "always"),
        ("低溫一配進貨：便當、微波食品、沙拉", "03:50", "🥶", "物流", 70, "always"),
        ("放玉米下去蒸", "04:00", "🌽", "熟食", 80, "always"),
        ("鮮一進貨：麵包、飯糰", "05:20", "🍞", "物流", 90, "always"),
        ("常溫物流：常溫商品、飲料、泡麵、餅乾", "06:20", "🚚", "物流", 100, "always"),
        ("交班", "07:00", "🤝", "交班", 110, "always"),
    ]
    xn_id = _template_id(db, "溪洲大夜班工作範本", "溪洲大夜班工作流程")
    _replace_items(db, xn_id, xizhou_night)
    db.execute("UPDATE shift_types SET template_id=? WHERE name='溪洲大夜'", (xn_id,))

    # 物流時間與內容。既有同名資料直接更新，避免建立重複項目。
    logistics = [
        ("日翊", "📦", "03:40", "04:10", "包裹", 1, 1, 0, 1, 10),
        ("低溫一配", "🥶", "03:50", "04:30", "便當、微波食品、沙拉", 1, 1, 0, 1, 10),
        ("鮮一", "🍞", "05:20", "06:00", "麵包、飯糰", 1, 1, 0, 1, 10),
        ("常溫物流", "🚚", "06:20", "07:30", "常溫商品、飲料、泡麵、餅乾", 1, 1, 0, 1, 10),
    ]
    # 舊名稱「常溫」轉成「常溫物流」，若新名稱已存在則停用舊項目。
    old = db.execute("SELECT id FROM logistics_settings WHERE name='常溫'").fetchone()
    new = db.execute("SELECT id FROM logistics_settings WHERE name='常溫物流'").fetchone()
    if old and not new:
        db.execute("UPDATE logistics_settings SET name='常溫物流' WHERE id=?", (old["id"],))
    elif old and new:
        db.execute("UPDATE logistics_settings SET is_active=0 WHERE id=?", (old["id"],))

    active_names=[]
    for row in logistics:
        name, icon, start, end, content, applies_b, applies_c, applies_late, applies_night, remind_minutes = row
        active_names.append(name)
        db.execute(
            """INSERT INTO logistics_settings
            (name,icon,start_time,end_time,content,applies_b,applies_c,applies_late,applies_night,remind_minutes,line_push,show_carousel,is_active,updated_at)
            VALUES (?,?,?,?,?,?,?,?,?,?,1,1,1,CURRENT_TIMESTAMP)
            ON CONFLICT(name) DO UPDATE SET icon=excluded.icon,start_time=excluded.start_time,
            end_time=excluded.end_time,content=excluded.content,applies_b=excluded.applies_b,
            applies_c=excluded.applies_c,applies_late=excluded.applies_late,
            applies_night=excluded.applies_night,remind_minutes=excluded.remind_minutes,
            line_push=1,show_carousel=1,is_active=1,updated_at=CURRENT_TIMESTAMP""",
            (name,icon,start,end,content,applies_b,applies_c,applies_late,applies_night,remind_minutes)
        )
    db.execute("UPDATE logistics_settings SET is_active=0 WHERE name IN ('巧克力')")

    # 重新同步今天以後的班表；已完成的工作與物流進度保留。
    today = datetime.now().date().isoformat()
    shifts = db.execute(
        """SELECT s.*,st.store_code,st.start_time,st.template_id FROM shifts s
        JOIN shift_types st ON st.id=s.shift_type_id WHERE s.work_date>=?""", (today,)
    ).fetchall()
    for shift in shifts:
        if shift["template_id"]:
            desired=[]
            for item in db.execute("SELECT * FROM work_template_items WHERE template_id=? ORDER BY sort_order,id", (shift["template_id"],)):
                if not _condition_ok(item["condition_type"], shift["work_date"], bool(shift["manager_tasks"])):
                    continue
                desired.append(item["id"])
                existing=db.execute("SELECT id FROM daily_work_items WHERE work_date=? AND template_item_id=?", (shift["work_date"],item["id"])).fetchone()
                if existing:
                    db.execute("""UPDATE daily_work_items SET shift_id=?,title=?,scheduled_time=?,icon=?,category=? WHERE id=?""",
                               (shift["id"],item["title"],item["scheduled_time"],item["icon"],item["category"],existing["id"]))
                else:
                    db.execute("""INSERT INTO daily_work_items(work_date,shift_id,template_item_id,title,scheduled_time,icon,category)
                               VALUES (?,?,?,?,?,?,?)""",
                               (shift["work_date"],shift["id"],item["id"],item["title"],item["scheduled_time"],item["icon"],item["category"]))
            if desired:
                marks=",".join("?" for _ in desired)
                db.execute(f"""DELETE FROM daily_work_items WHERE work_date=? AND template_item_id IS NOT NULL
                           AND template_item_id NOT IN ({marks}) AND is_done=0""", (shift["work_date"],*desired))
        _sync_logistics(db, shift["work_date"], shift)

    db.execute("INSERT INTO schema_migrations(migration_key) VALUES (?)", (migration,))

def upsert_user(uid,name,pic):
    with connect() as db:
        db.execute("""INSERT INTO users(line_user_id,display_name,picture_url) VALUES (?,?,?)
        ON CONFLICT(line_user_id) DO UPDATE SET display_name=excluded.display_name,
        picture_url=excluded.picture_url,last_login_at=CURRENT_TIMESTAMP""",(uid,name,pic))

def list_shift_types():
    with connect() as db:
        return [dict(r) for r in db.execute("SELECT * FROM shift_types WHERE is_active=1 ORDER BY id")]

def list_shifts():
    with connect() as db:
        return [dict(r) for r in db.execute("""SELECT s.*,st.name shift_name,st.store_code,
        st.start_time,st.end_time,st.icon,st.color FROM shifts s
        JOIN shift_types st ON st.id=s.shift_type_id ORDER BY work_date""")]

def get_shift(work_date):
    with connect() as db:
        r=db.execute("""SELECT s.*,st.name shift_name,st.store_code,st.start_time,st.end_time,
        st.icon,st.color,st.template_id FROM shifts s JOIN shift_types st
        ON st.id=s.shift_type_id WHERE work_date=?""",(work_date,)).fetchone()
        return dict(r) if r else None

def _condition_ok(kind,work_date,manager):
    weekday=datetime.strptime(work_date,"%Y-%m-%d").weekday()
    return kind=="always" or (kind=="wed_sun" and weekday in (2,6)) or (kind=="sunday" and weekday==6) or (kind=="manager" and manager)

def _sync_logistics(db,work_date,shift):
    """同步當日物流，但不清空既有到店／完成紀錄。"""
    desired_ids=[]
    if shift["store_code"]!="X":
        mode = "late" if shift["start_time"]=="15:00" else "night"
        sql = "SELECT * FROM logistics_settings WHERE is_active=1 AND "
        sql += "applies_late=1" if mode=="late" else "applies_night=1"
        for item in db.execute(sql):
            if shift["store_code"]=="B" and not item["applies_b"]:
                continue
            if shift["store_code"]=="C" and not item["applies_c"]:
                continue
            desired_ids.append(item["id"])
            db.execute("INSERT OR IGNORE INTO daily_logistics(work_date,logistics_id) VALUES (?,?)",(work_date,item["id"]))
    # 只移除尚未有任何進度、且已不適用的自動物流；已到店或已完成紀錄永久保留。
    if desired_ids:
        marks=",".join("?" for _ in desired_ids)
        db.execute(f"""DELETE FROM daily_logistics WHERE work_date=?
        AND logistics_id NOT IN ({marks}) AND arrived_at IS NULL AND completed_at IS NULL""",
        (work_date,*desired_ids))
    else:
        db.execute("""DELETE FROM daily_logistics WHERE work_date=?
        AND arrived_at IS NULL AND completed_at IS NULL""",(work_date,))

def save_shift(work_date,shift_type_id,overtime=False,overtime_end="",manager_tasks=False,note=""):
    with connect() as db:
        st=db.execute("SELECT * FROM shift_types WHERE id=?",(shift_type_id,)).fetchone()
        if not st:
            raise ValueError("班別不存在")
        db.execute("""INSERT INTO shifts(work_date,shift_type_id,overtime,overtime_end,manager_tasks,note)
        VALUES (?,?,?,?,?,?) ON CONFLICT(work_date) DO UPDATE SET
        shift_type_id=excluded.shift_type_id,overtime=excluded.overtime,
        overtime_end=excluded.overtime_end,manager_tasks=excluded.manager_tasks,
        note=excluded.note,updated_at=CURRENT_TIMESTAMP""",
        (work_date,shift_type_id,int(bool(overtime)),overtime_end or None,int(bool(manager_tasks)),note))
        shift_id=db.execute("SELECT id FROM shifts WHERE work_date=?",(work_date,)).fetchone()["id"]
        desired_template_ids=[]
        if st["template_id"]:
            for item in db.execute("SELECT * FROM work_template_items WHERE template_id=? ORDER BY sort_order,id",(st["template_id"],)):
                if not _condition_ok(item["condition_type"],work_date,manager_tasks):
                    continue
                desired_template_ids.append(item["id"])
                existing=db.execute("""SELECT id,is_done FROM daily_work_items
                WHERE work_date=? AND template_item_id=?""",(work_date,item["id"])).fetchone()
                if existing:
                    # 更新排程文字，但保留完成狀態與完成時間。
                    db.execute("""UPDATE daily_work_items SET shift_id=?,title=?,scheduled_time=?,icon=?,category=?
                    WHERE id=?""",(shift_id,item["title"],item["scheduled_time"],item["icon"],item["category"],existing["id"]))
                else:
                    db.execute("""INSERT INTO daily_work_items
                    (work_date,shift_id,template_item_id,title,scheduled_time,icon,category)
                    VALUES (?,?,?,?,?,?,?)""",
                    (work_date,shift_id,item["id"],item["title"],item["scheduled_time"],item["icon"],item["category"]))
        # 班別改變時，只移除舊班別尚未完成的自動項目；手動項目與已完成項目保留。
        if desired_template_ids:
            marks=",".join("?" for _ in desired_template_ids)
            db.execute(f"""DELETE FROM daily_work_items WHERE work_date=?
            AND template_item_id IS NOT NULL AND template_item_id NOT IN ({marks}) AND is_done=0""",
            (work_date,*desired_template_ids))
        else:
            db.execute("""DELETE FROM daily_work_items WHERE work_date=?
            AND template_item_id IS NOT NULL AND is_done=0""",(work_date,))
        _sync_logistics(db,work_date,st)
        db.commit()

    # 使用全新連線驗證，避免只更新到目前請求的暫存畫面。
    saved = get_shift(work_date)
    if not saved or int(saved["shift_type_id"]) != int(shift_type_id):
        raise OSError("班表未能寫入永久資料庫，請稍後再試。")
    return saved

def delete_shift(work_date):
    with connect() as db:
        db.execute("DELETE FROM daily_work_items WHERE work_date=?",(work_date,))
        db.execute("DELETE FROM daily_logistics WHERE work_date=?",(work_date,))
        db.execute("DELETE FROM shifts WHERE work_date=?",(work_date,))

def list_daily_work(work_date):
    with connect() as db:
        return [dict(r) for r in db.execute("SELECT * FROM daily_work_items WHERE work_date=? ORDER BY scheduled_time,id",(work_date,))]

def toggle_daily_work(item_id):
    with connect() as db:
        r=db.execute("SELECT is_done FROM daily_work_items WHERE id=?",(item_id,)).fetchone()
        if r:
            value=0 if r["is_done"] else 1
            db.execute("""UPDATE daily_work_items SET is_done=?,
            completed_at=CASE WHEN ?=1 THEN CURRENT_TIMESTAMP ELSE NULL END WHERE id=?""",(value,value,item_id))

def list_logistics_settings():
    with connect() as db:
        return [dict(r) for r in db.execute("SELECT * FROM logistics_settings ORDER BY start_time,id")]

def save_logistics_setting(item_id,name,icon,start_time,end_time,content,applies_b,applies_c,applies_late,applies_night,remind_minutes,line_push,show_carousel,is_active):
    name = (name or "").strip()
    if not name:
        raise ValueError("物流名稱不能空白")
    with connect() as db:
        existing = db.execute("SELECT id FROM logistics_settings WHERE name=?", (name,)).fetchone()
        if item_id:
            # 名稱若與另一筆重複，保留目前編輯項目並回報可讀錯誤，不讓整頁 500。
            if existing and existing["id"] != item_id:
                raise ValueError("已有相同名稱的物流設定，請更換名稱")
            result = db.execute("""UPDATE logistics_settings SET name=?,icon=?,start_time=?,end_time=?,
            content=?,applies_b=?,applies_c=?,applies_late=?,applies_night=?,
            remind_minutes=?,line_push=?,show_carousel=?,is_active=?,updated_at=CURRENT_TIMESTAMP
            WHERE id=?""",(name,icon,start_time,end_time,content,applies_b,applies_c,
            applies_late,applies_night,remind_minutes,line_push,show_carousel,is_active,item_id))
            if result.rowcount == 0:
                raise ValueError("找不到要修改的物流設定")
        elif existing:
            # 「新增」不可暗中覆蓋同名舊資料，避免使用者以為建立新項目卻改掉原資料。
            raise ValueError("已有相同名稱的物流設定；要修改請按該項目的『編輯』，或使用不同名稱")
        else:
            db.execute("""INSERT INTO logistics_settings
            (name,icon,start_time,end_time,content,applies_b,applies_c,applies_late,
            applies_night,remind_minutes,line_push,show_carousel,is_active)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",(name,icon,start_time,end_time,content,
            applies_b,applies_c,applies_late,applies_night,remind_minutes,line_push,show_carousel,is_active))

def delete_logistics_setting(item_id):
    with connect() as db:
        db.execute("DELETE FROM logistics_settings WHERE id=?",(item_id,))

def list_daily_logistics(work_date):
    with connect() as db:
        return [dict(r) for r in db.execute("""SELECT d.*,l.name,l.icon,l.start_time,l.end_time,
        l.content,l.remind_minutes,l.line_push,l.show_carousel FROM daily_logistics d
        JOIN logistics_settings l ON l.id=d.logistics_id WHERE d.work_date=?
        ORDER BY l.start_time,l.id""",(work_date,))]

def logistics_arrive(item_id):
    with connect() as db:
        db.execute("UPDATE daily_logistics SET arrived_at=CURRENT_TIMESTAMP WHERE id=?",(item_id,))

def logistics_complete(item_id):
    with connect() as db:
        db.execute("UPDATE daily_logistics SET completed_at=CURRENT_TIMESTAMP WHERE id=?",(item_id,))

def mark_logistics_reminded(item_id):
    with connect() as db:
        db.execute("UPDATE daily_logistics SET reminded_at=CURRENT_TIMESTAMP WHERE id=?", (item_id,))

def attendance_for(work_date):
    with connect() as db:
        r=db.execute("SELECT * FROM attendance WHERE work_date=?",(work_date,)).fetchone()
        return dict(r) if r else None

def check_in(work_date):
    with connect() as db:
        shift=db.execute("SELECT id FROM shifts WHERE work_date=?",(work_date,)).fetchone()
        db.execute("""INSERT INTO attendance(work_date,shift_id,check_in_at) VALUES (?,?,CURRENT_TIMESTAMP)
        ON CONFLICT(work_date) DO UPDATE SET check_in_at=CURRENT_TIMESTAMP,updated_at=CURRENT_TIMESTAMP""",
        (work_date,shift["id"] if shift else None))

def check_out(work_date):
    with connect() as db:
        db.execute("""INSERT INTO attendance(work_date,check_out_at) VALUES (?,CURRENT_TIMESTAMP)
        ON CONFLICT(work_date) DO UPDATE SET check_out_at=CURRENT_TIMESTAMP,updated_at=CURRENT_TIMESTAMP""",(work_date,))

def add_reminder(title,reminder_type,remind_date,remind_time,note="",related_url="/dashboard",line_push=1,show_carousel=1):
    with connect() as db:
        db.execute("""INSERT INTO reminders(title,reminder_type,remind_date,remind_time,note,
        related_url,line_push,show_carousel) VALUES (?,?,?,?,?,?,?,?)""",
        (title,reminder_type,remind_date,remind_time,note,related_url,line_push,show_carousel))

def list_reminders(include_done=True):
    sql="SELECT * FROM reminders"
    if not include_done:
        sql+=" WHERE is_done=0"
    sql+=" ORDER BY remind_date,remind_time,id"
    with connect() as db:return [dict(r) for r in db.execute(sql)]

def due_reminders(today,now_time):
    with connect() as db:
        return [dict(r) for r in db.execute("""SELECT * FROM reminders WHERE is_done=0
        AND sent_at IS NULL AND line_push=1 AND remind_date=? AND remind_time<=?
        ORDER BY remind_time,id""",(today,now_time))]

def mark_reminder_sent(item_id):
    with connect() as db:db.execute("UPDATE reminders SET sent_at=CURRENT_TIMESTAMP WHERE id=?",(item_id,))

def complete_reminder(item_id):
    with connect() as db:db.execute("UPDATE reminders SET is_done=1 WHERE id=?",(item_id,))

def delete_reminder(item_id):
    with connect() as db:db.execute("DELETE FROM reminders WHERE id=?",(item_id,))

def add_notification_log(title,content,status):
    with connect() as db:
        db.execute("INSERT INTO notification_logs(title,content,status) VALUES (?,?,?)",(title,content,status))

def list_notification_logs():
    with connect() as db:return [dict(r) for r in db.execute("SELECT * FROM notification_logs ORDER BY id DESC LIMIT 100")]

def add_task(title,due_date="",note=""):
    title=(title or "").strip()
    if not title:
        raise ValueError("請輸入待辦事項")
    with connect() as db:
        cur=db.execute("INSERT INTO tasks(title,due_date,note) VALUES (?,?,?) RETURNING id",(title,due_date or None,(note or "").strip()))
        item_id=cur.fetchone()["id"]
        db.commit()
    with connect() as db:
        saved=db.execute("SELECT * FROM tasks WHERE id=?",(item_id,)).fetchone()
    if not saved:
        raise OSError("待辦事項未能寫入永久資料庫，請稍後再試。")
    return dict(saved)

def list_tasks(show_done=True):
    sql="SELECT * FROM tasks"
    if not show_done:sql+=" WHERE is_done=0"
    sql+=" ORDER BY is_done,COALESCE(due_date,'9999-12-31'),id DESC"
    with connect() as db:return [dict(r) for r in db.execute(sql)]

def toggle_task(item_id):
    with connect() as db:
        r=db.execute("SELECT is_done FROM tasks WHERE id=?",(item_id,)).fetchone()
        if r:
            v=0 if r["is_done"] else 1
            db.execute("""UPDATE tasks SET is_done=?,completed_at=CASE WHEN ?=1 THEN CURRENT_TIMESTAMP ELSE NULL END WHERE id=?""",(v,v,item_id))

def delete_task(item_id):
    with connect() as db:db.execute("DELETE FROM tasks WHERE id=?",(item_id,))

def add_work_log(work_date,category,title,amount=0,note=""):
    with connect() as db:db.execute("INSERT INTO work_logs(work_date,category,title,amount,note) VALUES (?,?,?,?,?)",(work_date,category,title,amount,note))

def list_work_logs():
    with connect() as db:return [dict(r) for r in db.execute("SELECT * FROM work_logs ORDER BY work_date DESC,id DESC")]

def delete_work_log(item_id):
    with connect() as db:db.execute("DELETE FROM work_logs WHERE id=?",(item_id,))

def dashboard_counts(work_date):
    with connect() as db:
        total=db.execute("SELECT COUNT(*) c FROM daily_work_items WHERE work_date=?",(work_date,)).fetchone()["c"]
        done=db.execute("SELECT COUNT(*) c FROM daily_work_items WHERE work_date=? AND is_done=1",(work_date,)).fetchone()["c"]
        pending=db.execute("SELECT COUNT(*) c FROM tasks WHERE is_done=0").fetchone()["c"]
        shortage=db.execute("SELECT COALESCE(SUM(amount),0) s FROM work_logs WHERE work_date=? AND category='短收'",(work_date,)).fetchone()["s"]
        logistics=db.execute("SELECT COUNT(*) c FROM daily_logistics WHERE work_date=?",(work_date,)).fetchone()["c"]
        logistics_done=db.execute("SELECT COUNT(*) c FROM daily_logistics WHERE work_date=? AND completed_at IS NOT NULL",(work_date,)).fetchone()["c"]
    return {"work_total":total,"work_done":done,"pending_tasks":pending,"shortage_total":shortage,"logistics_total":logistics,"logistics_done":logistics_done}

def set_setting(key,value):
    with connect() as db:
        db.execute("""INSERT INTO app_settings(setting_key,setting_value) VALUES (?,?)
        ON CONFLICT(setting_key) DO UPDATE SET setting_value=excluded.setting_value,updated_at=CURRENT_TIMESTAMP""",(key,value))

def get_setting(key,default=""):
    with connect() as db:
        r=db.execute("SELECT setting_value FROM app_settings WHERE setting_key=?",(key,)).fetchone()
        return r["setting_value"] if r else default


def add_activity(title, activity_date, activity_time="", location="", note="", line_push=True, remind_minutes=30):
    now=datetime.now().isoformat(timespec="seconds")
    with connect() as db:
        db.execute(
            """INSERT INTO activities(title,activity_date,activity_time,location,note,line_push,remind_minutes,is_done,created_at,updated_at,reminded_at)
               VALUES (?,?,?,?,?,?,?,0,?,?,NULL)""",
            (title,activity_date,activity_time or "",location or "",note or "",1 if line_push else 0,max(int(remind_minutes or 0),0),now,now)
        )


def get_activity(item_id):
    with connect() as db:
        row=db.execute("SELECT * FROM activities WHERE id=?",(item_id,)).fetchone()
        return dict(row) if row else None


def update_activity(item_id,title,activity_date,activity_time="",location="",note="",line_push=True,remind_minutes=30):
    now=datetime.now().isoformat(timespec="seconds")
    with connect() as db:
        db.execute(
            """UPDATE activities SET title=?,activity_date=?,activity_time=?,location=?,note=?,line_push=?,
               remind_minutes=?,updated_at=?,reminded_at=NULL WHERE id=?""",
            (title,activity_date,activity_time or "",location or "",note or "",1 if line_push else 0,
             max(int(remind_minutes or 0),0),now,item_id)
        )


def complete_activity(item_id, done=True):
    with connect() as db:
        db.execute("UPDATE activities SET is_done=?,updated_at=CURRENT_TIMESTAMP WHERE id=?",(1 if done else 0,item_id))


def delete_activity(item_id):
    with connect() as db:
        db.execute("DELETE FROM activities WHERE id=?",(item_id,))


def mark_activity_reminded(item_id):
    with connect() as db:
        db.execute("UPDATE activities SET reminded_at=CURRENT_TIMESTAMP,updated_at=CURRENT_TIMESTAMP WHERE id=?",(item_id,))


def due_activities(now_date, now_time):
    now=datetime.strptime(f"{now_date} {now_time}","%Y-%m-%d %H:%M")
    due=[]
    with connect() as db:
        rows=db.execute("""SELECT * FROM activities
                           WHERE is_done=0 AND line_push=1 AND reminded_at IS NULL
                             AND activity_date BETWEEN ? AND ?
                           ORDER BY activity_date, CASE WHEN activity_time='' THEN '09:00' ELSE activity_time END""",
                        ((now.date()-timedelta(days=2)).isoformat(),(now.date()+timedelta(days=2)).isoformat())).fetchall()
    for row in rows:
        item=dict(row)
        event_time=item.get("activity_time") or "09:00"
        try:
            event_at=datetime.strptime(f"{item['activity_date']} {event_time}","%Y-%m-%d %H:%M")
        except ValueError:
            continue
        remind_at=event_at-timedelta(minutes=int(item.get("remind_minutes") or 0))
        if remind_at <= now < event_at+timedelta(minutes=5):
            item["event_time"]=event_time
            due.append(item)
    return due


def list_activities(include_done=True, limit=100):
    sql="SELECT * FROM activities"
    params=[]
    if not include_done:
        sql += " WHERE is_done=0"
    sql += " ORDER BY activity_date ASC, CASE WHEN activity_time='' THEN '23:59' ELSE activity_time END ASC, id ASC LIMIT ?"
    params.append(limit)
    with connect() as db:
        return [dict(row) for row in db.execute(sql,params).fetchall()]


def upcoming_activities(today, limit=5):
    with connect() as db:
        rows=db.execute(
            """SELECT * FROM activities WHERE is_done=0 AND activity_date>=?
               ORDER BY activity_date ASC, CASE WHEN activity_time='' THEN '23:59' ELSE activity_time END ASC, id ASC LIMIT ?""",
            (today,limit)
        ).fetchall()
        return [dict(row) for row in rows]
