"""Background jobs.

Jobs live in the database, so they survive restarts: a job that was running
when the process died is queued again on startup (or parked as paused, see
Settings) and continues from the last record it finished. Records are the
checkpoint: each one is claimed atomically, processed, and written back on
its own, so several workers or several users can never collide.

Job types: scan, transcribe, import, export, download.
"""
import json
import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor, wait

from sat import audio, db, engines, notify, scanner
from sat.engines import local as local_engines

log = logging.getLogger("sat.jobs")

ACTIVE = ("queued", "running", "paused")


class JobPaused(Exception):
    pass


class JobCancelled(Exception):
    pass


class JobContext:
    def __init__(self, row, flags):
        self.id = row["id"]
        self.type = row["type"]
        self.project_id = row["project_id"]
        self.created_by = row["created_by"]
        self.params = json.loads(row["params"] or "{}")
        self.flags = flags
        self._lock = threading.Lock()
        self.done = row["done"] or 0
        self.failed = row["failed"] or 0
        self.total = row["total"] or 0
        self._last_write = 0.0

    def check(self):
        if self.flags["cancel"].is_set():
            raise JobCancelled()
        if self.flags["pause"].is_set():
            raise JobPaused()

    def stopping(self):
        return self.flags["cancel"].is_set() or self.flags["pause"].is_set()

    def log(self, message, level="info"):
        getattr(log, level if level in ("debug", "info", "warning", "error") else "info")("job %s: %s", self.id, message)
        try:
            db.insert("job_logs", {"job_id": self.id, "level": level, "message": str(message)[:4000], "created_at": db.now()})
        except Exception:
            pass

    def progress(self, done=None, total=None, failed=None, message=None, force=False):
        with self._lock:
            if done is not None:
                self.done = done
            if total is not None:
                self.total = total
            if failed is not None:
                self.failed = failed
            now = time.time()
            if not force and now - self._last_write < 0.5 and message is None:
                return
            self._last_write = now
            values = {"done": self.done, "total": self.total, "failed": self.failed, "updated_at": db.now()}
            if message is not None:
                values["message"] = str(message)[:500]
            db.update("jobs", self.id, values)

    def inc(self, failed=False):
        with self._lock:
            if failed:
                self.failed += 1
            else:
                self.done += 1
        self.progress()


class JobRunner:
    def __init__(self):
        self.flags = {}
        self.threads = {}
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread = None

    # Lifecycle ----------------------------------------------------------------

    def start(self):
        self.recover()
        self._thread = threading.Thread(target=self._loop, name="job-scheduler", daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()

    def recover(self):
        """Put interrupted work back in the queue after a crash or restart."""
        auto = db.get_setting("auto_resume_jobs")
        stamp = db.now()
        with db.transaction() as conn:
            conn.execute("UPDATE records SET status='pending', updated_at=? WHERE status='processing'", (stamp,))
            conn.execute("UPDATE records SET claimed_by=NULL, claimed_at=NULL WHERE claimed_by IS NOT NULL")
            new_status = "queued" if auto else "paused"
            conn.execute(
                "UPDATE jobs SET status=?, message='interrupted by a restart, ' || ?, updated_at=? WHERE status='running'",
                (new_status, "resuming" if auto else "waiting for resume", stamp),
            )

    # Public API ------------------------------------------------------------------

    def enqueue(self, job_type, params=None, project_id=None, title="", created_by=None, total=0):
        return db.insert(
            "jobs",
            {
                "project_id": project_id,
                "type": job_type,
                "status": "queued",
                "title": title or job_type,
                "total": total,
                "params": json.dumps(params or {}),
                "created_by": created_by,
                "created_at": db.now(),
                "updated_at": db.now(),
            },
        )

    def pause(self, job_id):
        job = db.query_one("SELECT * FROM jobs WHERE id=?", (job_id,))
        if not job:
            return False
        if job["status"] == "queued":
            db.update("jobs", job_id, {"status": "paused", "message": "paused", "updated_at": db.now()})
            return True
        if job["status"] == "running":
            flags = self.flags.get(job_id)
            if flags:
                flags["pause"].set()
            return True
        return False

    def resume(self, job_id):
        job = db.query_one("SELECT * FROM jobs WHERE id=?", (job_id,))
        if not job or job["status"] not in ("paused", "failed", "cancelled"):
            return False
        db.update("jobs", job_id, {"status": "queued", "message": "resuming", "updated_at": db.now(), "finished_at": None})
        return True

    def cancel(self, job_id):
        job = db.query_one("SELECT * FROM jobs WHERE id=?", (job_id,))
        if not job:
            return False
        if job["status"] in ("queued", "paused"):
            db.update("jobs", job_id, {"status": "cancelled", "message": "cancelled", "finished_at": db.now(), "updated_at": db.now()})
            return True
        if job["status"] == "running":
            flags = self.flags.get(job_id)
            if flags:
                flags["cancel"].set()
            return True
        return False

    def active_for_project(self, project_id, types=None):
        sql = "SELECT * FROM jobs WHERE project_id=? AND status IN ('queued','running','paused')"
        params = [project_id]
        if types:
            sql += " AND type IN (%s)" % ",".join("?" for _ in types)
            params += list(types)
        return db.query(sql + " ORDER BY id", params)

    # Scheduler ---------------------------------------------------------------

    def _loop(self):
        last_minute = 0
        while not self._stop.is_set():
            try:
                self._start_queued()
                if time.time() - last_minute > 60:
                    last_minute = time.time()
                    self._minute_tasks()
            except Exception:
                log.exception("scheduler error")
            self._stop.wait(1.0)

    def _running_jobs(self):
        with self._lock:
            return [jid for jid, t in self.threads.items() if t.is_alive()]

    def _uses_local_model(self, job):
        if job["type"] == "download":
            return True
        if job["type"] != "transcribe":
            return False
        params = json.loads(job["params"] or "{}")
        engine_id = params.get("provider")
        if not engine_id and job["project_id"]:
            p = db.query_one("SELECT provider FROM projects WHERE id=?", (job["project_id"],))
            engine_id = p["provider"] if p else None
        try:
            return engines.get(engine_id)["kind"] == "local"
        except ValueError:
            return False

    def _start_queued(self):
        running_ids = self._running_jobs()
        try:
            limit = int(db.get_setting("max_parallel_jobs") or 2)
        except (TypeError, ValueError):
            limit = 2
        if len(running_ids) >= limit:
            return
        running = db.query("SELECT * FROM jobs WHERE status='running'")
        local_busy = any(self._uses_local_model(j) for j in running)
        busy_projects = {j["project_id"] for j in running if j["type"] in ("scan", "import")}
        for job in db.query("SELECT * FROM jobs WHERE status='queued' ORDER BY id"):
            if len(self._running_jobs()) >= limit:
                break
            if self._uses_local_model(job) and local_busy:
                continue
            if job["type"] in ("scan", "import", "transcribe") and job["project_id"] in busy_projects:
                continue
            self._spawn(job)
            if self._uses_local_model(job):
                local_busy = True
            if job["type"] in ("scan", "import"):
                busy_projects.add(job["project_id"])

    def _spawn(self, job):
        flags = {"pause": threading.Event(), "cancel": threading.Event()}
        with self._lock:
            self.flags[job["id"]] = flags
        db.update("jobs", job["id"], {"status": "running", "started_at": job["started_at"] or db.now(), "updated_at": db.now(), "message": "starting"})
        t = threading.Thread(target=self._run, args=(job["id"], flags), name="job-%s" % job["id"], daemon=True)
        with self._lock:
            self.threads[job["id"]] = t
        t.start()

    def _run(self, job_id, flags):
        row = db.query_one("SELECT * FROM jobs WHERE id=?", (job_id,))
        ctx = JobContext(row, flags)
        handler = HANDLERS.get(ctx.type)
        status, message, result = "completed", "done", {}
        try:
            if handler is None:
                raise RuntimeError("unknown job type %s" % ctx.type)
            result = handler(ctx) or {}
            message = result.get("message", "done")
        except JobPaused:
            status, message = "paused", "paused"
        except JobCancelled:
            status, message = "cancelled", "cancelled"
        except Exception as exc:
            log.exception("job %s failed", job_id)
            status, message = "failed", str(exc)[:500]
            ctx.log(str(exc), level="error")
        values = {"status": status, "message": message, "result": json.dumps(result, default=str), "updated_at": db.now(),
                  "done": ctx.done, "failed": ctx.failed, "total": ctx.total}
        if status in ("completed", "failed", "cancelled"):
            values["finished_at"] = db.now()
        db.update("jobs", job_id, values)
        with self._lock:
            self.flags.pop(job_id, None)
            self.threads.pop(job_id, None)
        self._announce(row, ctx, status, message, result)
        db.close()

    def _announce(self, row, ctx, status, message, result):
        if status == "paused":
            return
        title = row["title"] or row["type"]
        level = {"completed": "success", "failed": "danger", "cancelled": "warning"}.get(status, "info")
        link = "/projects/%d" % row["project_id"] if row["project_id"] else "/jobs"
        summary = message if status != "completed" else (result.get("summary") or "finished")
        notify.notify("%s %s" % (title, status), summary, level=level, user_id=row["created_by"], link=link, job_id=row["id"])
        if status == "completed" and row["type"] == "scan" and result.get("new") and row["created_by"] is None:
            notify.notify("New audio found", "%s new files in %s" % (result["new"], row["title"].replace("Scheduled scan: ", "")), level="info", link=link, job_id=row["id"])

    # Housekeeping every minute ----------------------------------------------------

    def _minute_tasks(self):
        local_engines.unload_if_idle()
        self._release_stale_claims()
        self._scheduled_scans()
        try:
            notify.prune()
            audio.trim_play_cache()
        except Exception:
            log.exception("housekeeping error")

    def _release_stale_claims(self):
        try:
            timeout = int(db.get_setting("claim_timeout_seconds") or 180)
        except (TypeError, ValueError):
            timeout = 180
        db.execute(
            "UPDATE records SET claimed_by=NULL, claimed_at=NULL WHERE claimed_at IS NOT NULL AND claimed_at < datetime('now', ?)",
            ("-%d seconds" % timeout,),
        )

    def _scheduled_scans(self):
        for p in db.query("SELECT * FROM projects WHERE watch_minutes > 0"):
            due = db.scalar(
                "SELECT 1 FROM projects WHERE id=? AND (last_scan_at IS NULL OR last_scan_at < datetime('now', ?))",
                (p["id"], "-%d minutes" % int(p["watch_minutes"])),
            )
            if not due:
                continue
            if self.active_for_project(p["id"], types=("scan", "import")):
                continue
            self.enqueue("scan", {"project_id": p["id"], "scheduled": True, "auto": bool(p["auto_transcribe"])}, project_id=p["id"], title="Scheduled scan: %s" % p["name"])


# Handlers -----------------------------------------------------------------------

def _project(ctx):
    pid = ctx.params.get("project_id") or ctx.project_id
    project = db.query_one("SELECT * FROM projects WHERE id=?", (pid,))
    if not project:
        raise RuntimeError("project %s no longer exists" % pid)
    return project


def run_scan(ctx):
    project = _project(ctx)
    ctx.log("scanning %s" % project["root_path"])
    summary = scanner.scan_project(project, job=ctx, check=ctx.check)
    if ctx.params.get("reprepare"):
        summary.update(scanner.reprepare_changed(project, job=ctx, check=ctx.check))
    text = "%d files, %d new, %d changed, %d missing" % (summary["found"], summary["new"], summary["changed"], summary["missing"])
    ctx.progress(message=text, force=True)
    if summary["new"] and (ctx.params.get("auto") or project["auto_transcribe"]):
        pending = db.scalar("SELECT COUNT(*) FROM records WHERE project_id=? AND status='pending'", (project["id"],))
        if pending:
            runner.enqueue("transcribe", {"project_id": project["id"]}, project_id=project["id"], title="Transcribe: %s" % project["name"], created_by=ctx.created_by, total=pending)
    summary["summary"] = text
    return summary


def _claim_next(project_id, record_ids=None):
    """Atomically take one pending record so parallel workers never share one."""
    where = "project_id=? AND status='pending'"
    params = [project_id]
    if record_ids:
        where += " AND id IN (%s)" % ",".join("?" for _ in record_ids)
        params += list(record_ids)
    with db.transaction() as conn:
        row = conn.execute(
            "UPDATE records SET status='processing', updated_at=? WHERE id=(SELECT id FROM records WHERE %s ORDER BY file_id, segment_index LIMIT 1) RETURNING *" % where,
            [db.now()] + params,
        ).fetchone()
    return dict(row) if row else None


def run_transcribe(ctx):
    project = _project(ctx)
    engine_id = ctx.params.get("provider") or project["provider"]
    model = ctx.params.get("model") or project["model"]
    language = ctx.params.get("language") if "language" in ctx.params else project["language"]
    language = (language or "").strip() or None
    engine = engines.get(engine_id)
    project_options = json.loads(project["options"] or "{}")
    options = engines.engine_options(engine_id, project_options.get("engine_options"))
    record_ids = ctx.params.get("record_ids") or None
    if record_ids:
        with db.transaction() as conn:
            marks = ",".join("?" for _ in record_ids)
            conn.execute("UPDATE records SET status='pending', error=NULL, updated_at=? WHERE id IN (%s) AND status<>'processing'" % marks, [db.now()] + list(record_ids))
    elif ctx.params.get("retry_failed"):
        db.execute("UPDATE records SET status='pending', error=NULL, updated_at=? WHERE project_id=? AND status='failed'", (db.now(), project["id"]))
    where = "project_id=? AND status='pending'"
    params = [project["id"]]
    if record_ids:
        where += " AND id IN (%s)" % ",".join("?" for _ in record_ids)
        params += list(record_ids)
    remaining = db.scalar("SELECT COUNT(*) FROM records WHERE " + where, params)
    using = "using %s / %s" % (engine["name"], model)
    ctx.progress(total=ctx.done + ctx.failed + remaining, message=using, force=True)
    ctx.log("engine %s, model %s, language %s, %d records to do" % (engine_id, model, language or "auto", remaining))
    if remaining == 0:
        return {"summary": "nothing to transcribe", "transcribed": 0}
    # The first record of a model that is not on disk yet waits for the download.
    # Say so, otherwise the job looks stuck at 0 for minutes.
    first_use = {"pending": engine["kind"] == "local" and not local_engines.is_downloaded(engine_id, model, options)}
    if first_use["pending"]:
        ctx.progress(message="downloading model %s, the first run takes a while" % model, force=True)
        ctx.log("model %s is not downloaded yet, downloading it now" % model)
    concurrency = 1
    if engine["kind"] == "api":
        try:
            concurrency = max(1, int(db.get_setting("api_concurrency") or 4))
        except (TypeError, ValueError):
            concurrency = 4
    stop_signal = {"exc": None}

    def worker():
        while True:
            if stop_signal["exc"] is not None:
                return
            try:
                ctx.check()
            except (JobPaused, JobCancelled) as exc:
                stop_signal["exc"] = exc
                return
            rec = _claim_next(project["id"], record_ids)
            if rec is None:
                return
            wav, temporary = None, False
            try:
                wav, temporary = audio.prepared_wav(rec)
                try:
                    res = engines.transcribe(engine_id, model, wav, language, options)
                finally:
                    if first_use["pending"]:
                        first_use["pending"] = False
                        ctx.progress(message=using, force=True)
                db.update(
                    "records",
                    rec["id"],
                    {
                        "text": res.get("text") or "",
                        "status": "done",
                        "provider": engine_id,
                        "model": model,
                        "detected_language": res.get("language"),
                        "error": None,
                        "attempts": (rec["attempts"] or 0) + 1,
                        "transcribed_at": db.now(),
                        "updated_at": db.now(),
                    },
                )
                ctx.inc()
            except Exception as exc:
                text = str(exc)[:1000]
                if _fatal(text):
                    # Configuration problem that would fail every record: stop the job
                    # and leave the record pending so a resume picks it up again.
                    db.update("records", rec["id"], {"status": "pending", "error": text, "updated_at": db.now()})
                    ctx.log("stopping: %s" % text, level="error")
                    stop_signal["exc"] = RuntimeError(text)
                    return
                db.update("records", rec["id"], {"status": "failed", "error": text, "attempts": (rec["attempts"] or 0) + 1, "updated_at": db.now()})
                ctx.inc(failed=True)
                ctx.log("record %s failed: %s" % (rec["id"], text), level="warning")
            finally:
                if temporary and wav is not None:
                    audio.discard_prepared(wav)

    if concurrency > 1:
        with ThreadPoolExecutor(max_workers=concurrency, thread_name_prefix="transcribe") as pool:
            futures = [pool.submit(_thread_wrap, worker) for _ in range(concurrency)]
            wait(futures)
    else:
        worker()
    if stop_signal["exc"] is not None:
        raise stop_signal["exc"]
    ctx.progress(force=True)
    left = db.scalar("SELECT COUNT(*) FROM records WHERE " + where, params)
    summary = "%d transcribed, %d failed" % (ctx.done, ctx.failed)
    return {"summary": summary, "transcribed": ctx.done, "failed": ctx.failed, "remaining": left}


def _thread_wrap(fn):
    try:
        fn()
    finally:
        db.close()


def _fatal(text):
    """Errors that will hit every record: stop the job instead of failing them all."""
    markers = ("API key is not set", "HTTP 401", "HTTP 403", "was not found. Install ffmpeg", "not installed", "No module named", "gated", "base URL is not set")
    return any(m in text for m in markers)


def run_download(ctx):
    engine_id = ctx.params["engine"]
    model = ctx.params["model"]
    options = ctx.params.get("options") or {}
    ctx.log("downloading %s model %s" % (engine_id, model))

    def progress(done, total):
        ctx.progress(done=done, total=total or done, message="%.0f MB%s" % (done / 1e6, (" of %.0f MB" % (total / 1e6)) if total else ""))

    repo = local_engines.download(engine_id, model, options, progress=progress, stop=ctx.stopping)
    ctx.check()
    return {"summary": "downloaded %s" % repo, "repo": repo}


def run_import(ctx):
    from sat import dataset
    return dataset.run_import(ctx)


def run_export(ctx):
    from sat import dataset
    return dataset.run_export(ctx)


HANDLERS = {
    "scan": run_scan,
    "transcribe": run_transcribe,
    "download": run_download,
    "import": run_import,
    "export": run_export,
}

runner = JobRunner()
