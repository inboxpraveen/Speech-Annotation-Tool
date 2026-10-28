"""Users, sessions and presence.

Accounts are created by an admin inside the app. The first admin comes from
ADMIN_USERNAME / ADMIN_PASSWORD in the environment. Presence is kept in
memory: every client pings /api/status a couple of times a minute and tells
us which page, project and record it is on.
"""
import logging
import threading
import time
from functools import wraps

from flask import g, jsonify, redirect, request, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash

from sat import db
from sat.config import ADMIN_PASSWORD, ADMIN_USERNAME

ONLINE_SECONDS = 45
DEFAULT_ADMIN_PASSWORD = "admin"

log = logging.getLogger("sat")

_presence = {}
_presence_lock = threading.Lock()


def public_user(row):
    if not row:
        return None
    return {
        "id": row["id"],
        "username": row["username"],
        "display_name": row["display_name"] or row["username"],
        "role": row["role"],
        "is_active": bool(row["is_active"]),
        "created_at": row["created_at"],
        "last_login_at": row["last_login_at"],
    }


def bootstrap_admin():
    if db.scalar("SELECT COUNT(*) FROM users") == 0:
        create_user(ADMIN_USERNAME, ADMIN_PASSWORD, role="admin", display_name="Admin")


def warn_default_admin():
    """Log a warning while the first admin still has the shipped default password."""
    row = db.query_one("SELECT password_hash FROM users WHERE username=? AND role='admin'", (ADMIN_USERNAME,))
    if row and check_password_hash(row["password_hash"], DEFAULT_ADMIN_PASSWORD):
        log.warning("The %s account still uses the default password. Change it from the user menu before sharing this server.", ADMIN_USERNAME)


def create_user(username, password, role="member", display_name=""):
    username = (username or "").strip()
    if not username:
        raise ValueError("username is required")
    if len(password or "") < 4:
        raise ValueError("password must be at least 4 characters")
    if role not in ("admin", "member"):
        raise ValueError("role must be admin or member")
    if db.query_one("SELECT id FROM users WHERE username=?", (username,)):
        raise ValueError("username already exists")
    return db.insert(
        "users",
        {
            "username": username,
            "display_name": display_name or username,
            "password_hash": generate_password_hash(password),
            "role": role,
            "is_active": 1,
            "created_at": db.now(),
        },
    )


def set_password(user_id, password):
    if len(password or "") < 4:
        raise ValueError("password must be at least 4 characters")
    db.update("users", user_id, {"password_hash": generate_password_hash(password)})


def authenticate(username, password):
    row = db.query_one("SELECT * FROM users WHERE username=?", ((username or "").strip(),))
    if not row or not row["is_active"]:
        return None
    if not check_password_hash(row["password_hash"], password or ""):
        return None
    db.update("users", row["id"], {"last_login_at": db.now()})
    return row


def current_user():
    if "user" in g:
        return g.user
    g.user = None
    uid = session.get("uid")
    if uid:
        row = db.query_one("SELECT * FROM users WHERE id=? AND is_active=1", (uid,))
        g.user = public_user(row)
    return g.user


def login_required(view):
    @wraps(view)
    def wrapper(*args, **kwargs):
        if current_user() is None:
            if request.path.startswith("/api/"):
                return jsonify({"error": "login required"}), 401
            return redirect(url_for("pages.login", next=request.path))
        return view(*args, **kwargs)

    return wrapper


def admin_required(view):
    @wraps(view)
    def wrapper(*args, **kwargs):
        user = current_user()
        if user is None:
            if request.path.startswith("/api/"):
                return jsonify({"error": "login required"}), 401
            return redirect(url_for("pages.login", next=request.path))
        if user["role"] != "admin":
            if request.path.startswith("/api/"):
                return jsonify({"error": "admin only"}), 403
            return redirect(url_for("pages.dashboard"))
        return view(*args, **kwargs)

    return wrapper


# Presence -------------------------------------------------------------------

def touch_presence(user, page=None, project_id=None, record_id=None):
    with _presence_lock:
        entry = _presence.get(user["id"], {})
        entry.update(
            {
                "user_id": user["id"],
                "username": user["username"],
                "display_name": user["display_name"],
                "last_seen": time.time(),
                "page": page or entry.get("page") or "",
                "project_id": project_id,
                "record_id": record_id,
            }
        )
        _presence[user["id"]] = entry


def drop_presence(user_id):
    with _presence_lock:
        _presence.pop(user_id, None)


def online_users():
    cutoff = time.time() - ONLINE_SECONDS
    with _presence_lock:
        rows = [dict(v) for v in _presence.values() if v["last_seen"] >= cutoff]
    rows.sort(key=lambda r: r["display_name"].lower())
    for r in rows:
        r["seconds_ago"] = int(time.time() - r.pop("last_seen"))
    return rows
