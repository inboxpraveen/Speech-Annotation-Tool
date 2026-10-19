"""JSON API used by the pages."""
import json
import os
import platform
import shutil
import string
from pathlib import Path

from flask import Blueprint, abort, jsonify, request, send_file
from werkzeug.utils import secure_filename

from sat import audio, auth, db, engines, notify
from sat.config import AUDIO_ROOTS, BASE_DIR, EXPORTS_DIR, IMPORTS_DIR, SEGMENTS_DIR
from sat.engines import api as api_engines
from sat.engines import local as local_engines
from sat.jobs import runner

bp = Blueprint("api", __name__, url_prefix="/api")

SAMPLE_WAV = BASE_DIR / "static" / "sample" / "sample.wav"


def body():
    data = request.get_json(silent=True)
    return data if isinstance(data, dict) else {}


def user():
    return auth.current_user()


def err(message, code=400):
    return jsonify({"error": message}), code


def page_args(default=50, maximum=500):
    try:
        page = max(1, int(request.args.get("page", 1)))
    except ValueError:
        page = 1
    try:
        per_page = min(maximum, max(1, int(request.args.get("per_page", default))))
    except ValueError:
        per_page = default
    return page, per_page


# Status, notifications, presence ------------------------------------------------

@bp.get("/status")
@auth.login_required
def status():
    u = user()
    project_id = request.args.get("project_id", type=int)
    record_id = request.args.get("record_id", type=int)
    auth.touch_presence(u, page=request.args.get("page"), project_id=project_id, record_id=record_id)
    jobs = db.query(
        "SELECT j.*, p.name AS project_name FROM jobs j LEFT JOIN projects p ON p.id=j.project_id "
        "WHERE j.status IN ('queued','running','paused') ORDER BY j.id DESC LIMIT 20"
    )
    latest, unread_count = notify.unread(u["id"], limit=5)
    out = {
        "time": db.now(),
        "user": u,
        "jobs": jobs,
        "notifications": {"unread": unread_count, "latest": latest},
        "online": auth.online_users(),
        "loaded_model": local_engines.loaded_model(),
        "poll_seconds": db.get_setting("status_poll_seconds") or 2,
    }
    if project_id:
        out["project"] = project_stats(project_id)
        out["project"]["claims"] = db.query(
            "SELECT r.id, r.claimed_by, u.display_name AS claimed_by_name FROM records r LEFT JOIN users u ON u.id=r.claimed_by "
            "WHERE r.project_id=? AND r.claimed_by IS NOT NULL",
            (project_id,),
        )
    return jsonify(out)


@bp.get("/notifications")
@auth.login_required
def notifications():
    return jsonify({"items": notify.recent(user()["id"])})


@bp.post("/notifications/read")
@auth.login_required
def notifications_read():
    notify.mark_read(user()["id"], body().get("ids"))
    return jsonify({"ok": True})


# File system browsing --------------------------------------------------------

def _roots():
    roots = []
    if platform.system() == "Windows":
        for letter in string.ascii_uppercase:
            drive = "%s:\\" % letter
            if os.path.exists(drive):
                roots.append({"name": drive, "path": drive})
    else:
        roots.append({"name": "/", "path": "/"})
        home = os.path.expanduser("~")
        if os.path.isdir(home):
            roots.append({"name": "home", "path": home})
    for extra in AUDIO_ROOTS:
        if os.path.isdir(extra):
            roots.insert(0, {"name": extra, "path": extra})
    return roots


@bp.get("/fs/list")
@auth.login_required
def fs_list():
    path = (request.args.get("path") or "").strip()
    exts = request.args.get("ext")
    wanted = {"." + e.strip().lower().lstrip(".") for e in exts.split(",")} if exts else None
    if not path:
        return jsonify({"path": "", "parent": None, "dirs": _roots(), "files": [], "roots": _roots()})
    p = Path(path).expanduser()
    if not p.is_dir():
        return err("folder does not exist: %s" % path, 404)
    dirs, files, audio_count = [], [], 0
    audio_exts = {"." + e.strip().lower() for e in (db.get_setting("audio_extensions") or "").split(",") if e.strip()}
    try:
        with os.scandir(p) as it:
            for entry in it:
                if entry.name.startswith("."):
                    continue
                try:
                    if entry.is_dir(follow_symlinks=False):
                        dirs.append({"name": entry.name, "path": entry.path})
                    elif entry.is_file():
                        ext = os.path.splitext(entry.name)[1].lower()
                        if ext in audio_exts:
                            audio_count += 1
                        if wanted and ext in wanted:
                            files.append({"name": entry.name, "path": entry.path, "size": entry.stat().st_size})
                except OSError:
                    continue
    except PermissionError:
        return err("permission denied", 403)
    dirs.sort(key=lambda d: d["name"].lower())
    files.sort(key=lambda d: d["name"].lower())
    parent = str(p.parent) if p.parent != p else None
    return jsonify({"path": str(p), "parent": parent, "dirs": dirs[:2000], "files": files[:2000], "audio_count": audio_count, "roots": _roots()})


# Settings ------------------------------------------------------------------------

@bp.get("/settings")
@auth.admin_required
def get_settings():
    values = db.all_settings()
    values = {k: v for k, v in values.items() if not k.startswith("provider.") and not k.startswith("engine.")}
    return jsonify({"settings": values, "defaults": db.DEFAULT_SETTINGS, "capabilities": local_engines.capabilities()})


@bp.put("/settings")
@auth.admin_required
def put_settings():
    data = body()
    for key, value in data.items():
        if key not in db.DEFAULT_SETTINGS:
            continue
        default = db.DEFAULT_SETTINGS[key]
        try:
            if isinstance(default, bool):
                value = value in (True, "true", "1", 1, "on")
            elif isinstance(default, int):
                value = int(value)
            elif isinstance(default, float):
                value = float(value)
            else:
                value = "" if value is None else str(value)
        except (TypeError, ValueError):
            return err("invalid value for %s" % key)
        db.set_setting(key, value)
    return jsonify({"ok": True})


# Users -----------------------------------------------------------------------------

@bp.get("/users")
@auth.login_required
def list_users():
    rows = [auth.public_user(r) for r in db.query("SELECT * FROM users ORDER BY username")]
    online = {o["user_id"]: o for o in auth.online_users()}
    for r in rows:
        r["online"] = r["id"] in online
        r["activity"] = online.get(r["id"])
    return jsonify({"items": rows})


@bp.post("/users")
@auth.admin_required
def create_user():
    data = body()
    try:
        uid = auth.create_user(data.get("username"), data.get("password"), data.get("role") or "member", data.get("display_name") or "")
    except ValueError as exc:
        return err(str(exc))
    return jsonify({"id": uid})


@bp.put("/users/<int:user_id>")
@auth.admin_required
def update_user(user_id):
    data = body()
    row = db.query_one("SELECT * FROM users WHERE id=?", (user_id,))
    if not row:
        return err("user not found", 404)
    values = {}
    if "display_name" in data:
        values["display_name"] = (data["display_name"] or "").strip() or row["username"]
    if "role" in data:
        if data["role"] not in ("admin", "member"):
            return err("role must be admin or member")
        if row["id"] == user()["id"] and data["role"] != "admin":
            return err("you cannot remove your own admin role")
        values["role"] = data["role"]
    if "is_active" in data:
        if row["id"] == user()["id"] and not data["is_active"]:
            return err("you cannot deactivate yourself")
        values["is_active"] = 1 if data["is_active"] in (True, "true", 1, "1") else 0
    if values:
        db.update("users", user_id, values)
    if data.get("password"):
        try:
            auth.set_password(user_id, data["password"])
        except ValueError as exc:
            return err(str(exc))
    return jsonify({"ok": True})


@bp.delete("/users/<int:user_id>")
@auth.admin_required
def delete_user(user_id):
    if user_id == user()["id"]:
        return err("you cannot delete yourself")
    db.execute("DELETE FROM users WHERE id=?", (user_id,))
    auth.drop_presence(user_id)
    return jsonify({"ok": True})


@bp.post("/me/password")
@auth.login_required
def change_password():
    data = body()
    row = db.query_one("SELECT * FROM users WHERE id=?", (user()["id"],))
    if not auth.authenticate(row["username"], data.get("current") or ""):
        return err("current password is wrong")
    try:
        auth.set_password(row["id"], data.get("password"))
    except ValueError as exc:
        return err(str(exc))
    return jsonify({"ok": True})


# Providers and engines -----------------------------------------------------------

@bp.get("/engines")
@auth.login_required
def list_engines():
    items = engines.catalog_with_status()
    for e in items:
        e["options_current"] = db.get_setting("engine.%s.options" % e["id"]) or {}
        if e["kind"] == "api":
            key = api_engines.setting(e["id"], "api_key")
            e["key_preview"] = ("*" * 6 + key[-4:]) if key else ""
    return jsonify({"items": items})


@bp.put("/engines/<engine_id>")
@auth.admin_required
def update_engine(engine_id):
    try:
        e = engines.get(engine_id)
    except ValueError:
        return err("unknown engine", 404)
    data = body()
    if e["kind"] == "api":
        if "api_key" in data and data["api_key"] is not None:
            db.set_setting("provider.%s.api_key" % engine_id, str(data["api_key"]).strip())
        if "base_url" in data:
            db.set_setting("provider.%s.base_url" % engine_id, str(data["base_url"] or "").strip())
        if "model" in data:
            db.set_setting("provider.%s.model" % engine_id, str(data["model"] or "").strip())
    if "options" in data and isinstance(data["options"], dict):
        db.set_setting("engine.%s.options" % engine_id, data["options"])
    if engine_id == "onnx_asr" and "quantization" in data:
        db.set_setting("engine.onnx_asr.quantization", data["quantization"] or "auto")
    return jsonify({"ok": True})


@bp.post("/engines/<engine_id>/test")
@auth.login_required
def test_engine(engine_id):
    try:
        e = engines.get(engine_id)
    except ValueError:
        return err("unknown engine", 404)
    data = body()
    model = data.get("model") or (api_engines.setting(engine_id, "model", e["default_model"]) if e["kind"] == "api" else e["default_model"])
    if not SAMPLE_WAV.exists():
        return err("sample audio is missing from static/sample")
    options = engines.engine_options(engine_id, data.get("options"))
    try:
        result = engines.transcribe(engine_id, model, SAMPLE_WAV, data.get("language") or None, options)
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)[:1000]})
    return jsonify({"ok": True, "model": model, "text": result.get("text"), "language": result.get("language")})


@bp.get("/engines/openrouter/models")
@auth.login_required
def openrouter_models():
    try:
        return jsonify({"items": api_engines.openrouter_audio_models()})
    except Exception as exc:
        return err(str(exc), 502)


# Local models --------------------------------------------------------------------

@bp.get("/models")
@auth.login_required
def list_models():
    catalog = [e for e in engines.catalog_with_status() if e["kind"] == "local"]
    for e in catalog:
        for m in e["models"]:
            m["downloaded"] = local_engines.is_downloaded(e["id"], m["id"]) if e["installed"] else False
    return jsonify(
        {
            "engines": catalog,
            "loaded": local_engines.loaded_model(),
            "cache": local_engines.cached_repos(),
            "capabilities": local_engines.capabilities(),
            "downloads": db.query("SELECT * FROM jobs WHERE type='download' AND status IN ('queued','running','paused') ORDER BY id"),
            "hf_token_set": bool(db.get_setting("hf_token")),
        }
    )


@bp.post("/models/download")
@auth.login_required
def download_model():
    data = body()
    engine_id, model = data.get("engine"), (data.get("model") or "").strip()
    try:
        e = engines.get(engine_id)
    except ValueError:
        return err("unknown engine", 404)
    if e["kind"] != "local" or not model:
        return err("engine and model are required")
    active = db.query_one(
        "SELECT id FROM jobs WHERE type='download' AND status IN ('queued','running') AND params LIKE ?",
        ('%"model": "' + model + '"%',),
    )
    if active:
        return jsonify({"job_id": active["id"], "already": True})
    jid = runner.enqueue("download", {"engine": engine_id, "model": model, "options": data.get("options") or {}}, title="Download %s" % model, created_by=user()["id"])
    return jsonify({"job_id": jid})


@bp.post("/models/delete")
@auth.admin_required
def delete_model():
    repo = (body().get("repo") or "").strip()
    if not repo:
        return err("repo is required")
    loaded = local_engines.loaded_model()
    if loaded:
        local_engines.unload()
    ok = local_engines.delete_repo(repo)
    return jsonify({"ok": ok})


@bp.post("/models/unload")
@auth.login_required
def unload_model():
    local_engines.unload()
    return jsonify({"ok": True})


# Projects ---------------------------------------------------------------------------

def project_stats(project_id):
    rows = db.query("SELECT status, review, COUNT(*) AS n, COALESCE(SUM(duration), 0) AS secs FROM records WHERE project_id=? GROUP BY status, review", (project_id,))
    stats = {"records": 0, "pending": 0, "processing": 0, "done": 0, "failed": 0, "skipped": 0,
             "reviewed": 0, "approved": 0, "rejected": 0, "unreviewed": 0, "seconds": 0.0}
    for r in rows:
        stats["records"] += r["n"]
        stats["seconds"] += r["secs"] or 0
        stats[r["status"]] = stats.get(r["status"], 0) + r["n"]
        if r["review"] == "none":
            stats["unreviewed"] += r["n"]
        else:
            stats[r["review"]] = stats.get(r["review"], 0) + r["n"]
    files = db.query("SELECT status, COUNT(*) AS n FROM files WHERE project_id=? GROUP BY status", (project_id,))
    stats["files"] = {r["status"]: r["n"] for r in files}
    stats["files"]["total"] = sum(stats["files"].values())
    stats["active_jobs"] = db.query("SELECT id, type, status, title, done, total, failed, message FROM jobs WHERE project_id=? AND status IN ('queued','running','paused') ORDER BY id", (project_id,))
    return stats


def _validate_project(data, existing=None):
    values = {}
    if "name" in data or existing is None:
        name = (data.get("name") or "").strip()
        if not name:
            raise ValueError("name is required")
        values["name"] = name
    if "root_path" in data or existing is None:
        root = (data.get("root_path") or "").strip()
        if not root or not Path(root).is_dir():
            raise ValueError("audio folder does not exist: %s" % root)
        values["root_path"] = str(Path(root).resolve())
    if "provider" in data:
        engines.get(data["provider"])
        values["provider"] = data["provider"]
    if "model" in data:
        values["model"] = (data.get("model") or "").strip()
    if "language" in data:
        values["language"] = (data.get("language") or "").strip()
    if "description" in data:
        values["description"] = (data.get("description") or "").strip()
    if "chunk_mode" in data:
        if data["chunk_mode"] not in ("none", "fixed", "silence"):
            raise ValueError("chunk_mode must be none, fixed or silence")
        values["chunk_mode"] = data["chunk_mode"]
    if "chunk_seconds" in data:
        try:
            values["chunk_seconds"] = max(1.0, float(data["chunk_seconds"]))
        except (TypeError, ValueError):
            raise ValueError("chunk_seconds must be a number")
    if "watch_minutes" in data:
        try:
            values["watch_minutes"] = max(0, int(data["watch_minutes"] or 0))
        except (TypeError, ValueError):
            raise ValueError("watch_minutes must be a whole number")
    if "auto_transcribe" in data:
        values["auto_transcribe"] = 1 if data["auto_transcribe"] in (True, "true", 1, "1") else 0
    if "options" in data:
        opts = data["options"] if isinstance(data["options"], dict) else {}
        values["options"] = json.dumps(opts)
    return values


@bp.get("/projects")
@auth.login_required
def list_projects():
    rows = db.query("SELECT p.*, u.display_name AS owner FROM projects p LEFT JOIN users u ON u.id=p.created_by ORDER BY p.updated_at DESC")
    for r in rows:
        r["stats"] = project_stats(r["id"])
        r["options"] = json.loads(r["options"] or "{}")
    return jsonify({"items": rows})


@bp.post("/projects")
@auth.login_required
def create_project():
    data = body()
    try:
        values = _validate_project(data)
    except ValueError as exc:
        return err(str(exc))
    values.setdefault("provider", "faster_whisper")
    values.setdefault("model", engines.get(values["provider"])["default_model"])
    values.setdefault("chunk_mode", db.get_setting("default_chunk_mode") or "none")
    values.setdefault("chunk_seconds", float(db.get_setting("default_chunk_seconds") or 20))
    values.update({"created_by": user()["id"], "created_at": db.now(), "updated_at": db.now()})
    pid = db.insert("projects", values)
    jid = runner.enqueue("scan", {"project_id": pid, "auto": bool(data.get("transcribe_after_scan"))}, project_id=pid, title="Scan: %s" % values["name"], created_by=user()["id"])
    return jsonify({"id": pid, "job_id": jid})


@bp.get("/projects/<int:project_id>")
@auth.login_required
def get_project(project_id):
    row = db.query_one("SELECT * FROM projects WHERE id=?", (project_id,))
    if not row:
        return err("project not found", 404)
    row["options"] = json.loads(row["options"] or "{}")
    row["stats"] = project_stats(project_id)
    return jsonify(row)


@bp.put("/projects/<int:project_id>")
@auth.login_required
def update_project(project_id):
    row = db.query_one("SELECT * FROM projects WHERE id=?", (project_id,))
    if not row:
        return err("project not found", 404)
    try:
        values = _validate_project(body(), existing=row)
    except ValueError as exc:
        return err(str(exc))
    values["updated_at"] = db.now()
    db.update("projects", project_id, values)
    return jsonify({"ok": True})


@bp.delete("/projects/<int:project_id>")
@auth.login_required
def delete_project(project_id):
    row = db.query_one("SELECT * FROM projects WHERE id=?", (project_id,))
    if not row:
        return err("project not found", 404)
    u = user()
    if u["role"] != "admin" and row["created_by"] != u["id"]:
        return err("only an admin or the owner can delete a project", 403)
    for j in runner.active_for_project(project_id):
        runner.cancel(j["id"])
    db.execute("DELETE FROM projects WHERE id=?", (project_id,))
    shutil.rmtree(SEGMENTS_DIR / str(project_id), ignore_errors=True)
    return jsonify({"ok": True})


@bp.post("/projects/<int:project_id>/scan")
@auth.login_required
def scan_project(project_id):
    row = db.query_one("SELECT * FROM projects WHERE id=?", (project_id,))
    if not row:
        return err("project not found", 404)
    if runner.active_for_project(project_id, types=("scan", "import")):
        return err("a scan or import is already running for this project", 409)
    data = body()
    jid = runner.enqueue("scan", {"project_id": project_id, "auto": bool(data.get("transcribe_after")), "reprepare": bool(data.get("reprepare"))}, project_id=project_id, title="Scan: %s" % row["name"], created_by=user()["id"])
    return jsonify({"job_id": jid})


@bp.post("/projects/<int:project_id>/transcribe")
@auth.login_required
def transcribe_project(project_id):
    row = db.query_one("SELECT * FROM projects WHERE id=?", (project_id,))
    if not row:
        return err("project not found", 404)
    data = body()
    params = {"project_id": project_id}
    for key in ("provider", "model", "language"):
        if data.get(key) not in (None, ""):
            params[key] = data[key]
    if data.get("record_ids"):
        params["record_ids"] = [int(i) for i in data["record_ids"]][:5000]
    if data.get("retry_failed"):
        params["retry_failed"] = True
    if data.get("provider"):
        try:
            engines.get(data["provider"])
        except ValueError:
            return err("unknown provider")
    if not params.get("record_ids") and runner.active_for_project(project_id, types=("transcribe",)):
        return err("a transcription job is already active for this project", 409)
    title = "Transcribe: %s" % row["name"]
    if params.get("record_ids"):
        title = "Re-transcribe %d records: %s" % (len(params["record_ids"]), row["name"])
    jid = runner.enqueue("transcribe", params, project_id=project_id, title=title, created_by=user()["id"])
    return jsonify({"job_id": jid})


@bp.get("/projects/<int:project_id>/files")
@auth.login_required
def project_files(project_id):
    page, per_page = page_args()
    where, args = ["f.project_id=?"], [project_id]
    if request.args.get("status"):
        where.append("f.status=?")
        args.append(request.args["status"])
    if request.args.get("q"):
        where.append("f.rel_path LIKE ?")
        args.append("%" + request.args["q"] + "%")
    sql_where = " AND ".join(where)
    total = db.scalar("SELECT COUNT(*) FROM files f WHERE " + sql_where, args)
    rows = db.query(
        "SELECT f.*, (SELECT COUNT(*) FROM records r WHERE r.file_id=f.id) AS records FROM files f WHERE %s ORDER BY f.rel_path LIMIT ? OFFSET ?" % sql_where,
        args + [per_page, (page - 1) * per_page],
    )
    return jsonify({"items": rows, "total": total, "page": page, "per_page": per_page})


# Records ------------------------------------------------------------------------------

RECORD_SQL = (
    "SELECT r.*, f.rel_path, f.status AS file_status, u.display_name AS updated_by_name, c.display_name AS claimed_by_name "
    "FROM records r JOIN files f ON f.id=r.file_id LEFT JOIN users u ON u.id=r.updated_by LEFT JOIN users c ON c.id=r.claimed_by "
)


@bp.get("/projects/<int:project_id>/records")
@auth.login_required
def list_records(project_id):
    page, per_page = page_args()
    where, args = ["r.project_id=?"], [project_id]
    status = request.args.get("status")
    if status:
        where.append("r.status IN (%s)" % ",".join("?" for _ in status.split(",")))
        args += status.split(",")
    review = request.args.get("review")
    if review:
        where.append("r.review IN (%s)" % ",".join("?" for _ in review.split(",")))
        args += review.split(",")
    if request.args.get("file_id", type=int):
        where.append("r.file_id=?")
        args.append(request.args.get("file_id", type=int))
    # The page refreshes rows it already shows by id, which skips the sort over the whole project.
    ids = [int(i) for i in (request.args.get("ids") or "").split(",") if i.strip().isdigit()][:500]
    if ids:
        where.append("r.id IN (%s)" % ",".join("?" for _ in ids))
        args += ids
    q = (request.args.get("q") or "").strip()
    if q:
        where.append("(r.text LIKE ? OR r.corrected_text LIKE ? OR f.rel_path LIKE ? OR r.notes LIKE ?)")
        args += ["%" + q + "%"] * 4
    if request.args.get("edited") == "1":
        where.append("r.corrected_text IS NOT NULL")
    if request.args.get("claimed") == "1":
        where.append("r.claimed_by IS NOT NULL")
    sort = request.args.get("sort") or "path"
    order = {"path": "f.rel_path, r.segment_index", "updated": "r.updated_at DESC", "id": "r.id", "duration": "r.duration DESC"}.get(sort, "f.rel_path, r.segment_index")
    sql_where = " AND ".join(where)
    # Only a search needs the files table; counting without the join is much faster on big projects.
    count_from = "records r JOIN files f ON f.id=r.file_id" if q else "records r"
    total = db.scalar("SELECT COUNT(*) FROM %s WHERE %s" % (count_from, sql_where), args)
    rows = db.query(RECORD_SQL + "WHERE %s ORDER BY %s LIMIT ? OFFSET ?" % (sql_where, order), args + [per_page, (page - 1) * per_page])
    return jsonify({"items": rows, "total": total, "page": page, "per_page": per_page})


@bp.get("/records/<int:record_id>")
@auth.login_required
def get_record(record_id):
    row = db.query_one(RECORD_SQL + "WHERE r.id=?", (record_id,))
    if not row:
        return err("record not found", 404)
    return jsonify(row)


@bp.put("/records/<int:record_id>")
@auth.login_required
def update_record(record_id):
    data = body()
    u = user()
    with db.transaction() as conn:
        row = conn.execute("SELECT * FROM records WHERE id=?", (record_id,)).fetchone()
        if not row:
            return err("record not found", 404)
        row = dict(row)
        if data.get("version") is not None and int(data["version"]) != row["version"]:
            fresh = db.query_one(RECORD_SQL + "WHERE r.id=?", (record_id,))
            return jsonify({"error": "this record was changed by someone else, reload it", "record": fresh}), 409
        if row["claimed_by"] and row["claimed_by"] != u["id"] and not data.get("force"):
            claimer = db.query_one("SELECT display_name FROM users WHERE id=?", (row["claimed_by"],))
            return jsonify({"error": "%s is editing this record" % (claimer["display_name"] if claimer else "someone")}), 409
        values = {"updated_by": u["id"], "updated_at": db.now(), "version": row["version"] + 1}
        history = None
        if "corrected_text" in data:
            new_text = data["corrected_text"]
            new_text = None if new_text is None else str(new_text)
            if new_text != row["corrected_text"]:
                values["corrected_text"] = new_text
                history = (row["corrected_text"] if row["corrected_text"] is not None else row["text"], new_text)
        if "review" in data:
            if data["review"] not in ("none", "reviewed", "approved", "rejected"):
                return err("review must be none, reviewed, approved or rejected")
            values["review"] = data["review"]
        elif history and row["review"] == "none":
            # A human edited the text: that counts as a review unless told otherwise.
            values["review"] = "reviewed"
        if "notes" in data:
            values["notes"] = str(data["notes"] or "")
        if "status" in data and data["status"] in ("pending", "skipped", "done"):
            values["status"] = data["status"]
        if data.get("release", True):
            values["claimed_by"] = None
            values["claimed_at"] = None
        keys = list(values.keys())
        conn.execute("UPDATE records SET %s WHERE id=?" % ", ".join("%s=?" % k for k in keys), [values[k] for k in keys] + [record_id])
        if history or "review" in data:
            conn.execute(
                "INSERT INTO record_history (record_id, user_id, old_text, new_text, review, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                (record_id, u["id"], history[0] if history else None, history[1] if history else None, values.get("review"), db.now()),
            )
    return jsonify(db.query_one(RECORD_SQL + "WHERE r.id=?", (record_id,)))


@bp.post("/records/<int:record_id>/claim")
@auth.login_required
def claim_record(record_id):
    u = user()
    with db.transaction() as conn:
        row = conn.execute("SELECT id, claimed_by, claimed_at FROM records WHERE id=?", (record_id,)).fetchone()
        if not row:
            return err("record not found", 404)
        if row["claimed_by"] and row["claimed_by"] != u["id"]:
            claimer = conn.execute("SELECT display_name FROM users WHERE id=?", (row["claimed_by"],)).fetchone()
            return jsonify({"ok": False, "claimed_by": row["claimed_by"], "claimed_by_name": claimer["display_name"] if claimer else "someone"}), 409
        conn.execute("UPDATE records SET claimed_by=?, claimed_at=? WHERE id=?", (u["id"], db.now(), record_id))
    return jsonify({"ok": True})


@bp.post("/records/<int:record_id>/release")
@auth.login_required
def release_record(record_id):
    db.execute("UPDATE records SET claimed_by=NULL, claimed_at=NULL WHERE id=? AND claimed_by=?", (record_id, user()["id"]))
    return jsonify({"ok": True})


@bp.get("/records/<int:record_id>/history")
@auth.login_required
def record_history(record_id):
    rows = db.query(
        "SELECT h.*, u.display_name AS user_name FROM record_history h LEFT JOIN users u ON u.id=h.user_id WHERE h.record_id=? ORDER BY h.id DESC LIMIT 100",
        (record_id,),
    )
    return jsonify({"items": rows})


@bp.post("/projects/<int:project_id>/records/bulk")
@auth.login_required
def bulk_records(project_id):
    data = body()
    ids = [int(i) for i in (data.get("ids") or [])][:5000]
    action = data.get("action")
    if not ids or action not in ("approve", "reject", "reset_review", "reset", "skip", "delete"):
        return err("ids and a valid action are required")
    marks = ",".join("?" for _ in ids)
    stamp = db.now()
    with db.transaction() as conn:
        if action == "delete":
            conn.execute("DELETE FROM records WHERE project_id=? AND id IN (%s)" % marks, [project_id] + ids)
        elif action == "reset":
            conn.execute("UPDATE records SET status='pending', error=NULL, updated_at=? WHERE project_id=? AND id IN (%s) AND status<>'processing'" % marks, [stamp, project_id] + ids)
        elif action == "skip":
            conn.execute("UPDATE records SET status='skipped', updated_at=? WHERE project_id=? AND id IN (%s) AND status<>'processing'" % marks, [stamp, project_id] + ids)
        else:
            review = {"approve": "approved", "reject": "rejected", "reset_review": "none"}[action]
            conn.execute("UPDATE records SET review=?, updated_by=?, updated_at=? WHERE project_id=? AND id IN (%s)" % marks, [review, user()["id"], stamp, project_id] + ids)
    return jsonify({"ok": True, "count": len(ids)})


@bp.get("/records/<int:record_id>/audio")
@auth.login_required
def record_audio(record_id):
    row = db.query_one("SELECT * FROM records WHERE id=?", (record_id,))
    if not row:
        abort(404)
    src = Path(row["audio_path"])
    if not src.exists():
        return err("audio file is missing", 404)
    try:
        path, mimetype = audio.playable_path(row)
    except audio.AudioError as exc:
        return err(str(exc), 500)
    return send_file(str(path), mimetype=mimetype, conditional=True, max_age=3600)


# Jobs ----------------------------------------------------------------------------------

@bp.get("/jobs")
@auth.login_required
def list_jobs():
    page, per_page = page_args(default=30)
    where, args = ["1=1"], []
    if request.args.get("status"):
        where.append("j.status IN (%s)" % ",".join("?" for _ in request.args["status"].split(",")))
        args += request.args["status"].split(",")
    if request.args.get("project_id", type=int):
        where.append("j.project_id=?")
        args.append(request.args.get("project_id", type=int))
    sql_where = " AND ".join(where)
    total = db.scalar("SELECT COUNT(*) FROM jobs j WHERE " + sql_where, args)
    rows = db.query(
        "SELECT j.*, p.name AS project_name, u.display_name AS created_by_name FROM jobs j LEFT JOIN projects p ON p.id=j.project_id "
        "LEFT JOIN users u ON u.id=j.created_by WHERE %s ORDER BY j.id DESC LIMIT ? OFFSET ?" % sql_where,
        args + [per_page, (page - 1) * per_page],
    )
    for r in rows:
        r["params"] = json.loads(r["params"] or "{}")
        r["result"] = json.loads(r["result"] or "{}")
    return jsonify({"items": rows, "total": total, "page": page})


@bp.get("/jobs/<int:job_id>")
@auth.login_required
def get_job(job_id):
    row = db.query_one("SELECT j.*, p.name AS project_name FROM jobs j LEFT JOIN projects p ON p.id=j.project_id WHERE j.id=?", (job_id,))
    if not row:
        return err("job not found", 404)
    row["params"] = json.loads(row["params"] or "{}")
    row["result"] = json.loads(row["result"] or "{}")
    return jsonify(row)


@bp.get("/jobs/<int:job_id>/logs")
@auth.login_required
def job_logs(job_id):
    after = request.args.get("after", 0, type=int)
    rows = db.query("SELECT * FROM job_logs WHERE job_id=? AND id>? ORDER BY id LIMIT 500", (job_id, after))
    return jsonify({"items": rows})


@bp.post("/jobs/<int:job_id>/<action>")
@auth.login_required
def job_action(job_id, action):
    fn = {"pause": runner.pause, "resume": runner.resume, "cancel": runner.cancel}.get(action)
    if fn is None:
        return err("unknown action", 404)
    if not fn(job_id):
        return err("job cannot be %sd in its current state" % action, 409)
    return jsonify({"ok": True})


@bp.delete("/jobs/<int:job_id>")
@auth.login_required
def delete_job(job_id):
    row = db.query_one("SELECT status FROM jobs WHERE id=?", (job_id,))
    if not row:
        return err("job not found", 404)
    if row["status"] in ("queued", "running"):
        return err("stop the job first", 409)
    db.execute("DELETE FROM jobs WHERE id=?", (job_id,))
    return jsonify({"ok": True})


@bp.post("/jobs/clear")
@auth.login_required
def clear_jobs():
    db.execute("DELETE FROM jobs WHERE status IN ('completed','failed','cancelled')")
    return jsonify({"ok": True})


# Import and export ------------------------------------------------------------------

@bp.post("/import/upload")
@auth.login_required
def import_upload():
    f = request.files.get("file")
    if not f or not f.filename:
        return err("no file uploaded")
    name = secure_filename(f.filename) or "upload.csv"
    IMPORTS_DIR.mkdir(parents=True, exist_ok=True)
    target = IMPORTS_DIR / ("%s_%s" % (db.now().replace(":", "").replace(" ", "_"), name))
    f.save(str(target))
    return jsonify({"path": str(target)})


@bp.post("/import/sniff")
@auth.login_required
def import_sniff():
    from sat import dataset
    path = (body().get("path") or "").strip()
    if not path or not Path(path).is_file():
        return err("file not found")
    try:
        return jsonify(dataset.sniff_columns(path))
    except Exception as exc:
        return err("could not read file: %s" % exc)


@bp.post("/projects/<int:project_id>/import")
@auth.login_required
def import_project(project_id):
    row = db.query_one("SELECT * FROM projects WHERE id=?", (project_id,))
    if not row:
        return err("project not found", 404)
    data = body()
    path = (data.get("path") or "").strip()
    if not path or not Path(path).is_file():
        return err("data file not found")
    mapping = data.get("mapping") or {}
    if not mapping.get("audio"):
        return err("choose the audio column")
    params = {"project_id": project_id, "path": path, "mapping": mapping, "mode": data.get("mode") or "add",
              "base_dir": data.get("base_dir") or "", "mark_reviewed": bool(data.get("mark_reviewed"))}
    jid = runner.enqueue("import", params, project_id=project_id, title="Import %s: %s" % (Path(path).name, row["name"]), created_by=user()["id"])
    return jsonify({"job_id": jid})


@bp.post("/projects/<int:project_id>/export")
@auth.login_required
def export_project(project_id):
    row = db.query_one("SELECT * FROM projects WHERE id=?", (project_id,))
    if not row:
        return err("project not found", 404)
    data = body()
    fmt = data.get("format") or "csv"
    if fmt not in ("csv", "xlsx", "jsonl", "audiofolder"):
        return err("format must be csv, xlsx, jsonl or audiofolder")
    params = {
        "project_id": project_id, "format": fmt, "text_source": data.get("text_source") or "best",
        "review": [r for r in (data.get("review") or []) if r in ("none", "reviewed", "approved", "rejected")],
        "status": [s for s in (data.get("status") or []) if s in ("pending", "done", "failed", "skipped")],
        "skip_empty": data.get("skip_empty", True), "name": data.get("name") or row["name"],
        "zip": bool(data.get("zip")), "convert_wav": bool(data.get("convert_wav")),
    }
    jid = runner.enqueue("export", params, project_id=project_id, title="Export %s: %s" % (fmt, row["name"]), created_by=user()["id"])
    return jsonify({"job_id": jid})


@bp.get("/exports")
@auth.login_required
def list_exports():
    items = []
    for p in sorted(EXPORTS_DIR.iterdir(), key=lambda p: p.stat().st_mtime, reverse=True) if EXPORTS_DIR.exists() else []:
        items.append({"name": p.name, "is_dir": p.is_dir(), "size": p.stat().st_size if p.is_file() else None, "modified": p.stat().st_mtime, "path": str(p)})
    return jsonify({"items": items[:200]})


@bp.get("/exports/<path:name>")
@auth.login_required
def download_export(name):
    target = (EXPORTS_DIR / name).resolve()
    if EXPORTS_DIR.resolve() not in target.parents or not target.is_file():
        abort(404)
    return send_file(str(target), as_attachment=True, conditional=True)


@bp.delete("/exports/<path:name>")
@auth.login_required
def delete_export(name):
    target = (EXPORTS_DIR / name).resolve()
    if EXPORTS_DIR.resolve() not in target.parents:
        abort(404)
    if target.is_dir():
        shutil.rmtree(target, ignore_errors=True)
    elif target.is_file():
        target.unlink()
    return jsonify({"ok": True})
