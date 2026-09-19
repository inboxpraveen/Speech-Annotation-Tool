"""Folder scanning and change detection.

A scan walks the project folder recursively (streaming, never building a
full list in memory), picks up audio files only, and compares size and
modification time with what is already known. New files get records
created (one per file, or one per chunk when chunking is on). Changed and
missing files are flagged rather than deleted so no review work is lost.
"""
import json
import os
import shutil
from pathlib import Path

from sat import audio, db
from sat.config import SEGMENTS_DIR

SKIP_DIRS = {"@eadir", "$recycle.bin", "system volume information", "__macosx", "node_modules", "__pycache__"}


def audio_extensions():
    raw = db.get_setting("audio_extensions") or ""
    return {"." + e.strip().lower().lstrip(".") for e in raw.split(",") if e.strip()}


def walk_audio(root, extensions):
    """Yield (rel_path, size, mtime) for every audio file under root."""
    root = Path(root)
    stack = [root]
    while stack:
        current = stack.pop()
        try:
            it = os.scandir(current)
        except (PermissionError, FileNotFoundError, OSError):
            continue
        with it:
            for entry in it:
                name = entry.name
                if name.startswith(".") or name.startswith("._"):
                    continue
                try:
                    if entry.is_dir(follow_symlinks=False):
                        if name.lower() not in SKIP_DIRS:
                            stack.append(Path(entry.path))
                        continue
                    if not entry.is_file(follow_symlinks=False):
                        continue
                    ext = os.path.splitext(name)[1].lower()
                    if ext not in extensions:
                        continue
                    st = entry.stat(follow_symlinks=False)
                except OSError:
                    continue
                rel = os.path.relpath(entry.path, root).replace(os.sep, "/")
                yield rel, st.st_size, st.st_mtime


def scan_project(project, job=None, check=None):
    """Synchronise the files table with the folder on disk.

    `job` is a JobContext used for progress and logs, `check` raises when
    the job is paused or cancelled. Returns a summary dict.
    """
    check = check or (lambda: None)
    log = job.log if job else (lambda *a, **k: None)
    root = Path(project["root_path"])
    if not root.is_dir():
        raise RuntimeError("project folder does not exist: %s" % root)
    exts = audio_extensions()
    known = {}
    for row in db.query("SELECT id, rel_path, size, mtime, status FROM files WHERE project_id=?", (project["id"],)):
        known[row["rel_path"]] = row
    seen = set()
    new_ids, changed, returned = [], 0, 0
    batch = []
    stamp = db.now()

    def flush():
        if not batch:
            return
        with db.transaction() as conn:
            for rel, size, mtime in batch:
                cur = conn.execute(
                    "INSERT INTO files (project_id, rel_path, size, mtime, status, created_at, updated_at) "
                    "VALUES (?, ?, ?, ?, 'new', ?, ?)",
                    (project["id"], rel, size, mtime, stamp, stamp),
                )
                new_ids.append(cur.lastrowid)
        batch.clear()

    count = 0
    for rel, size, mtime in walk_audio(root, exts):
        count += 1
        seen.add(rel)
        row = known.get(rel)
        if row is None:
            batch.append((rel, size, mtime))
            if len(batch) >= 500:
                flush()
                check()
                if job:
                    job.progress(message="discovered %d files, %d new" % (count, len(new_ids)))
            continue
        if row["status"] == "missing":
            db.update("files", row["id"], {"status": "ready" if row["size"] == size and abs(row["mtime"] - mtime) < 1 else "changed", "updated_at": stamp})
            returned += 1
        if row["size"] != size or abs(row["mtime"] - mtime) >= 1:
            if row["status"] != "new":
                db.update("files", row["id"], {"size": size, "mtime": mtime, "status": "changed", "updated_at": stamp})
                changed += 1
        if count % 2000 == 0:
            check()
            if job:
                job.progress(message="checked %d files" % count)
    flush()
    # Files that failed to prepare last time (ffmpeg missing, unreadable audio) get another go.
    retry_ids = [r["id"] for rel, r in known.items() if rel in seen and r["status"] in ("error", "new")]
    new_ids.extend(retry_ids)

    missing_ids = [r["id"] for rel, r in known.items() if rel not in seen and r["status"] != "missing"]
    if missing_ids:
        with db.transaction() as conn:
            for fid in missing_ids:
                conn.execute("UPDATE files SET status='missing', updated_at=? WHERE id=?", (stamp, fid))
    log("scan found %d audio files: %d new, %d changed, %d missing, %d returned, %d to retry" % (count, len(new_ids) - len(retry_ids), changed, len(missing_ids), returned, len(retry_ids)))

    # Phase two: create records for the new files (probe duration, chunk).
    if job:
        job.progress(done=0, total=len(new_ids), message="preparing %d new files" % len(new_ids))
    prepared = failed = 0
    for i, fid in enumerate(new_ids):
        check()
        f = db.query_one("SELECT * FROM files WHERE id=?", (fid,))
        if not f:
            continue
        try:
            prepare_file(project, f)
            prepared += 1
        except Exception as exc:
            failed += 1
            db.update("files", fid, {"status": "error", "error": str(exc)[:500], "updated_at": db.now()})
            log("could not prepare %s: %s" % (f["rel_path"], exc), level="warning")
        if job and (i % 10 == 0 or i == len(new_ids) - 1):
            job.progress(done=i + 1, failed=failed, message="prepared %d of %d new files" % (i + 1, len(new_ids)))
    db.update("projects", project["id"], {"last_scan_at": db.now()})
    return {"found": count, "new": len(new_ids) - len(retry_ids), "changed": changed, "missing": len(missing_ids), "prepared": prepared, "failed": failed}


def prepare_file(project, f):
    """Create the records for one file according to the project chunk mode."""
    abs_path = Path(project["root_path"]) / f["rel_path"]
    duration = audio.probe_duration(abs_path)
    stamp = db.now()
    mode = project.get("chunk_mode") or "none"
    options = json.loads(project.get("options") or "{}")
    with db.transaction() as conn:
        conn.execute("DELETE FROM records WHERE file_id=? AND status='pending' AND corrected_text IS NULL", (f["id"],))
        existing = conn.execute("SELECT COUNT(*) FROM records WHERE file_id=?", (f["id"],)).fetchone()[0]
    if existing:
        db.update("files", f["id"], {"duration": duration, "status": "ready", "error": None, "updated_at": stamp})
        return
    chunk_seconds = float(project.get("chunk_seconds") or 30)
    # Short files are never chunked; silence mode tolerates a bit of overshoot.
    short = duration is not None and duration <= chunk_seconds * (1.5 if mode == "silence" else 1.0)
    if mode == "none" or duration is None or short:
        rows = [(0, None, None, duration, str(abs_path))]
    else:
        out_dir = SEGMENTS_DIR / str(project["id"]) / str(f["id"])
        if out_dir.exists():
            shutil.rmtree(out_dir, ignore_errors=True)
        pieces = audio.segment_file(
            abs_path, out_dir, mode, project.get("chunk_seconds") or 30,
            threshold_db=options.get("silence_threshold_db", db.get_setting("silence_threshold_db")),
            min_silence=options.get("min_silence_seconds", db.get_setting("min_silence_seconds")),
            duration=duration,
        )
        rows = [(idx, s, e, round(e - s, 3), str(p)) for idx, s, e, p in pieces]
    with db.transaction() as conn:
        for idx, s, e, dur, path in rows:
            conn.execute(
                "INSERT INTO records (project_id, file_id, segment_index, start_sec, end_sec, duration, audio_path, "
                "status, review, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, 'pending', 'none', ?, ?)",
                (project["id"], f["id"], idx, s, e, dur, path, stamp, stamp),
            )
        conn.execute("UPDATE files SET duration=?, status='ready', error=NULL, updated_at=? WHERE id=?", (duration, stamp, f["id"]))


def reprepare_changed(project, job=None, check=None):
    """Rebuild records for files flagged as changed.

    Unchunked projects keep the record (and any corrected text) and simply
    queue it for transcription again. Chunked projects get fresh segments.
    """
    check = check or (lambda: None)
    rows = db.query("SELECT * FROM files WHERE project_id=? AND status='changed'", (project["id"],))
    done = 0
    stamp = db.now()
    for f in rows:
        check()
        try:
            if (project.get("chunk_mode") or "none") == "none":
                duration = audio.probe_duration(Path(project["root_path"]) / f["rel_path"])
                with db.transaction() as conn:
                    conn.execute(
                        "UPDATE records SET status='pending', text='', error=NULL, duration=?, updated_at=? WHERE file_id=?",
                        (duration, stamp, f["id"]),
                    )
                    conn.execute("UPDATE files SET status='ready', duration=?, error=NULL, updated_at=? WHERE id=?", (duration, stamp, f["id"]))
            else:
                with db.transaction() as conn:
                    conn.execute("DELETE FROM records WHERE file_id=?", (f["id"],))
                seg_dir = SEGMENTS_DIR / str(project["id"]) / str(f["id"])
                if seg_dir.exists():
                    shutil.rmtree(seg_dir, ignore_errors=True)
                prepare_file(project, f)
        except Exception as exc:
            db.update("files", f["id"], {"status": "error", "error": str(exc)[:500], "updated_at": db.now()})
        done += 1
        if job:
            job.progress(done=done, total=len(rows), message="re-prepared %d of %d changed files" % (done, len(rows)))
    return {"reprepared": done}
