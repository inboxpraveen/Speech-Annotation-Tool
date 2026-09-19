"""SQLite storage.

One database file, WAL mode, one connection per thread and a process wide
write lock so concurrent users and background workers never trip over each
other. Every list endpoint paginates; nothing loads a whole table.
"""
import json
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, timezone

from sat.config import DB_PATH

_local = threading.local()
_write_lock = threading.RLock()

SCHEMA_VERSION = 1

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT NOT NULL UNIQUE COLLATE NOCASE,
    display_name TEXT NOT NULL DEFAULT '',
    password_hash TEXT NOT NULL,
    role TEXT NOT NULL DEFAULT 'member',
    is_active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL,
    last_login_at TEXT
);

CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS projects (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    root_path TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    provider TEXT NOT NULL DEFAULT 'faster_whisper',
    model TEXT NOT NULL DEFAULT 'base',
    language TEXT NOT NULL DEFAULT '',
    chunk_mode TEXT NOT NULL DEFAULT 'none',
    chunk_seconds REAL NOT NULL DEFAULT 30,
    options TEXT NOT NULL DEFAULT '{}',
    watch_minutes INTEGER NOT NULL DEFAULT 0,
    auto_transcribe INTEGER NOT NULL DEFAULT 0,
    created_by INTEGER,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    last_scan_at TEXT
);

CREATE TABLE IF NOT EXISTS files (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    rel_path TEXT NOT NULL,
    size INTEGER NOT NULL DEFAULT 0,
    mtime REAL NOT NULL DEFAULT 0,
    duration REAL,
    status TEXT NOT NULL DEFAULT 'new',
    error TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(project_id, rel_path)
);
CREATE INDEX IF NOT EXISTS idx_files_project_status ON files(project_id, status);

CREATE TABLE IF NOT EXISTS records (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    file_id INTEGER NOT NULL REFERENCES files(id) ON DELETE CASCADE,
    segment_index INTEGER NOT NULL DEFAULT 0,
    start_sec REAL,
    end_sec REAL,
    duration REAL,
    audio_path TEXT NOT NULL,
    text TEXT NOT NULL DEFAULT '',
    corrected_text TEXT,
    status TEXT NOT NULL DEFAULT 'pending',
    review TEXT NOT NULL DEFAULT 'none',
    provider TEXT,
    model TEXT,
    detected_language TEXT,
    error TEXT,
    attempts INTEGER NOT NULL DEFAULT 0,
    notes TEXT NOT NULL DEFAULT '',
    version INTEGER NOT NULL DEFAULT 1,
    claimed_by INTEGER,
    claimed_at TEXT,
    updated_by INTEGER,
    updated_at TEXT NOT NULL,
    created_at TEXT NOT NULL,
    transcribed_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_records_project_status ON records(project_id, status);
CREATE INDEX IF NOT EXISTS idx_records_project_review ON records(project_id, review);
CREATE INDEX IF NOT EXISTS idx_records_file ON records(file_id);

CREATE TABLE IF NOT EXISTS record_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    record_id INTEGER NOT NULL REFERENCES records(id) ON DELETE CASCADE,
    user_id INTEGER,
    old_text TEXT,
    new_text TEXT,
    review TEXT,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_history_record ON record_history(record_id);

CREATE TABLE IF NOT EXISTS jobs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER REFERENCES projects(id) ON DELETE CASCADE,
    type TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'queued',
    title TEXT NOT NULL DEFAULT '',
    total INTEGER NOT NULL DEFAULT 0,
    done INTEGER NOT NULL DEFAULT 0,
    failed INTEGER NOT NULL DEFAULT 0,
    message TEXT NOT NULL DEFAULT '',
    params TEXT NOT NULL DEFAULT '{}',
    result TEXT NOT NULL DEFAULT '{}',
    created_by INTEGER,
    created_at TEXT NOT NULL,
    started_at TEXT,
    finished_at TEXT,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(status);

CREATE TABLE IF NOT EXISTS job_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id INTEGER NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
    level TEXT NOT NULL,
    message TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_job_logs_job ON job_logs(job_id);

CREATE TABLE IF NOT EXISTS notifications (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    level TEXT NOT NULL DEFAULT 'info',
    title TEXT NOT NULL,
    message TEXT NOT NULL DEFAULT '',
    link TEXT,
    job_id INTEGER,
    created_at TEXT NOT NULL,
    read_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_notifications_user ON notifications(user_id, read_at);
"""


def now():
    """UTC timestamp in the same shape SQLite's datetime('now') produces."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def connect():
    """Return the calling thread's connection, opening it on first use."""
    conn = getattr(_local, "conn", None)
    if conn is None:
        conn = sqlite3.connect(str(DB_PATH), timeout=30, check_same_thread=False, isolation_level=None)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA busy_timeout=30000")
        _local.conn = conn
    return conn


def close():
    conn = getattr(_local, "conn", None)
    if conn is not None:
        conn.close()
        _local.conn = None


def init_db():
    if sqlite3.sqlite_version_info < (3, 35):
        raise RuntimeError("SQLite 3.35 or newer is required, found %s" % sqlite3.sqlite_version)
    conn = connect()
    with _write_lock:
        # executescript manages its own transaction, so it stays outside transaction().
        conn.executescript(SCHEMA)
        conn.execute("PRAGMA user_version=%d" % SCHEMA_VERSION)


@contextmanager
def transaction():
    """Serialised write transaction. Nest freely; the lock is re-entrant."""
    conn = connect()
    with _write_lock:
        nested = conn.in_transaction
        if not nested:
            conn.execute("BEGIN IMMEDIATE")
        try:
            yield conn
            if not nested:
                conn.execute("COMMIT")
        except Exception:
            if not nested:
                conn.execute("ROLLBACK")
            raise


def query(sql, params=()):
    return [dict(r) for r in connect().execute(sql, params).fetchall()]


def query_one(sql, params=()):
    row = connect().execute(sql, params).fetchone()
    return dict(row) if row else None


def scalar(sql, params=()):
    row = connect().execute(sql, params).fetchone()
    return row[0] if row else None


def execute(sql, params=()):
    """Run a write statement inside its own transaction and return the cursor."""
    with transaction() as conn:
        return conn.execute(sql, params)


def insert(table, values):
    keys = list(values.keys())
    sql = "INSERT INTO %s (%s) VALUES (%s)" % (table, ", ".join(keys), ", ".join("?" for _ in keys))
    with transaction() as conn:
        cur = conn.execute(sql, [values[k] for k in keys])
        return cur.lastrowid


def update(table, row_id, values):
    if not values:
        return
    keys = list(values.keys())
    sql = "UPDATE %s SET %s WHERE id=?" % (table, ", ".join("%s=?" % k for k in keys))
    with transaction() as conn:
        conn.execute(sql, [values[k] for k in keys] + [row_id])


# Settings -----------------------------------------------------------------

DEFAULT_SETTINGS = {
    "audio_extensions": "wav,mp3,flac,ogg,oga,opus,m4a,aac,wma,aiff,aif,amr,webm,mp4",
    "max_parallel_jobs": 2,
    "api_concurrency": 4,
    "local_device": "auto",
    "compute_type": "auto",
    "cpu_threads": 0,
    "unload_idle_minutes": 20,
    "hf_token": "",
    "ffmpeg_path": "",
    "default_chunk_mode": "silence",
    "default_chunk_seconds": 20,
    "silence_threshold_db": -35,
    "min_silence_seconds": 0.4,
    "claim_timeout_seconds": 180,
    "job_log_lines": 2000,
    "auto_resume_jobs": True,
    "status_poll_seconds": 2,
    "play_cache_mb": 1000,
}


def get_setting(key, default=None):
    row = query_one("SELECT value FROM settings WHERE key=?", (key,))
    if row is None:
        return DEFAULT_SETTINGS.get(key, default)
    try:
        return json.loads(row["value"])
    except (TypeError, ValueError):
        return row["value"]


def set_setting(key, value):
    with transaction() as conn:
        conn.execute(
            "INSERT INTO settings (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, json.dumps(value)),
        )


def all_settings(prefix=None):
    rows = query("SELECT key, value FROM settings")
    out = dict(DEFAULT_SETTINGS) if prefix is None else {}
    for r in rows:
        if prefix and not r["key"].startswith(prefix):
            continue
        try:
            out[r["key"]] = json.loads(r["value"])
        except (TypeError, ValueError):
            out[r["key"]] = r["value"]
    return out
