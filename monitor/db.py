import json
import sqlite3
from datetime import datetime
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent.parent / "data" / "monitor.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS notes (
    note_id      TEXT PRIMARY KEY,
    user_id      TEXT NOT NULL,
    nickname     TEXT,
    title        TEXT,
    desc         TEXT,
    note_type    TEXT,
    publish_time INTEGER,
    ip_location  TEXT,
    tags         TEXT,
    note_url     TEXT,
    cover_url    TEXT,
    liked_count     INTEGER DEFAULT 0,
    collected_count INTEGER DEFAULT 0,
    comment_count   INTEGER DEFAULT 0,
    share_count     INTEGER DEFAULT 0,
    detail_fetched  INTEGER DEFAULT 0,
    first_seen_at   TEXT,
    detail_json     TEXT
);
CREATE INDEX IF NOT EXISTS idx_notes_user ON notes(user_id);
CREATE TABLE IF NOT EXISTS note_metrics (
    note_id      TEXT NOT NULL,
    snapshot_at  TEXT NOT NULL,
    liked_count     INTEGER,
    collected_count INTEGER,
    comment_count   INTEGER,
    share_count     INTEGER,
    PRIMARY KEY (note_id, snapshot_at)
);
CREATE TABLE IF NOT EXISTS run_history (
    run_at        TEXT PRIMARY KEY,
    status        TEXT,
    new_notes     INTEGER,
    checked_users INTEGER,
    errors        TEXT,
    duration_s    REAL
);
"""


def connect():
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout=30000")
    return conn


def init_db():
    conn = connect()
    conn.executescript(SCHEMA)
    cols = {r["name"] for r in conn.execute("PRAGMA table_info(notes)").fetchall()}
    if "cobrand" not in cols:
        conn.execute("ALTER TABLE notes ADD COLUMN cobrand TEXT DEFAULT ''")
    conn.commit()
    conn.close()


def now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def known_note_ids(conn, user_id: str) -> dict:
    rows = conn.execute("SELECT note_id, detail_fetched FROM notes WHERE user_id=?", (user_id,)).fetchall()
    return {r["note_id"]: bool(r["detail_fetched"]) for r in rows}


def upsert_note(conn, n: dict, detail_fetched: bool):
    conn.execute(
        """INSERT INTO notes (note_id, user_id, nickname, title, desc, note_type, publish_time,
             ip_location, tags, note_url, cover_url, liked_count, collected_count,
             comment_count, share_count, detail_fetched, first_seen_at, detail_json, cobrand)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
           ON CONFLICT(note_id) DO UPDATE SET
             liked_count=excluded.liked_count,
             collected_count=excluded.collected_count,
             comment_count=excluded.comment_count,
             share_count=excluded.share_count,
             detail_fetched=MAX(notes.detail_fetched, excluded.detail_fetched),
             detail_json=COALESCE(excluded.detail_json, notes.detail_json),
             desc=COALESCE(excluded.desc, notes.desc),
             tags=COALESCE(excluded.tags, notes.tags),
             cobrand=COALESCE(NULLIF(excluded.cobrand,''), notes.cobrand)""",
        (
            n["note_id"], n["user_id"], n.get("nickname"), n.get("title"), n.get("desc"),
            n.get("note_type"), n.get("publish_time"), n.get("ip_location"), n.get("tags"),
            n.get("note_url"), n.get("cover_url"),
            n.get("liked_count", 0), n.get("collected_count", 0),
            n.get("comment_count", 0), n.get("share_count", 0),
            1 if detail_fetched else 0, now(),
            json.dumps(n["raw"], ensure_ascii=False) if n.get("raw") else None,
            n.get("cobrand", ""),
        ),
    )


def insert_metrics(conn, note_id: str, liked=0, collected=0, comment=0, share=0):
    conn.execute(
        "INSERT OR IGNORE INTO note_metrics VALUES (?,?,?,?,?,?)",
        (note_id, now(), liked, collected, comment, share),
    )


def last_snapshot(conn, note_id: str):
    row = conn.execute(
        """SELECT * FROM note_metrics WHERE note_id=? AND snapshot_at !=
             (SELECT MAX(snapshot_at) FROM note_metrics WHERE note_id=?)
           ORDER BY snapshot_at DESC LIMIT 1""",
        (note_id, note_id),
    ).fetchone()
    return dict(row) if row else None


def new_notes_this_run(conn, run_at: str):
    rows = conn.execute(
        "SELECT * FROM notes WHERE first_seen_at >= ? ORDER BY user_id, publish_time DESC",
        (run_at,),
    ).fetchall()
    return [dict(r) for r in rows]


def record_run(conn, run_at: str, status: str, new_notes: int, checked_users: int, errors: str, duration_s: float):
    conn.execute(
        "INSERT OR REPLACE INTO run_history VALUES (?,?,?,?,?,?)",
        (run_at, status, new_notes, checked_users, errors, duration_s),
    )
    conn.commit()
