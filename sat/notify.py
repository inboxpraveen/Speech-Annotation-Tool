"""In-app notifications.

Rows are per user. A broadcast simply writes one row per active user, which
keeps read state trivial. The status poll returns unread counts and the
latest few so the UI can show toasts and the bell dropdown.
"""
from sat import db


def notify(title, message="", level="info", user_id=None, link=None, job_id=None):
    stamp = db.now()
    if user_id is None:
        targets = [r["id"] for r in db.query("SELECT id FROM users WHERE is_active=1")]
    else:
        targets = [user_id]
    with db.transaction() as conn:
        for uid in targets:
            conn.execute(
                "INSERT INTO notifications (user_id, level, title, message, link, job_id, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (uid, level, title, message, link, job_id, stamp),
            )


def unread(user_id, limit=20):
    rows = db.query(
        "SELECT * FROM notifications WHERE user_id=? AND read_at IS NULL ORDER BY id DESC LIMIT ?",
        (user_id, limit),
    )
    count = db.scalar("SELECT COUNT(*) FROM notifications WHERE user_id=? AND read_at IS NULL", (user_id,))
    return rows, count


def recent(user_id, limit=50):
    return db.query("SELECT * FROM notifications WHERE user_id=? ORDER BY id DESC LIMIT ?", (user_id, limit))


def mark_read(user_id, ids=None):
    stamp = db.now()
    with db.transaction() as conn:
        if ids:
            marks = ",".join("?" for _ in ids)
            conn.execute("UPDATE notifications SET read_at=? WHERE user_id=? AND id IN (%s)" % marks, [stamp, user_id] + list(ids))
        else:
            conn.execute("UPDATE notifications SET read_at=? WHERE user_id=? AND read_at IS NULL", (stamp, user_id))


def prune(keep_days=30):
    db.execute("DELETE FROM notifications WHERE read_at IS NOT NULL AND created_at < datetime('now', ?)", ("-%d days" % keep_days,))
