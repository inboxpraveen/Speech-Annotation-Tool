import threading
import time

from sat import db, engines, scanner
from sat.jobs import JobContext, JobPaused, run_transcribe, runner


def _project_with_records(client, audio_dir, name):
    r = client.post("/api/projects", json={"name": name, "root_path": str(audio_dir), "chunk_mode": "none", "provider": "faster_whisper", "model": "tiny"})
    pid = r.get_json()["id"]
    runner.cancel(r.get_json()["job_id"])  # the runner is not started in tests
    scanner.scan_project(db.query_one("SELECT * FROM projects WHERE id=?", (pid,)))
    return pid


def _ctx(job_type, params, flags=None):
    jid = runner.enqueue(job_type, params, project_id=params.get("project_id"), title="t")
    flags = flags or {"pause": threading.Event(), "cancel": threading.Event()}
    return JobContext(db.query_one("SELECT * FROM jobs WHERE id=?", (jid,)), flags), flags


def test_pause_mid_job_leaves_no_record_processing(client, audio_dir, monkeypatch):
    pid = _project_with_records(client, audio_dir, "pause")
    flags = {"pause": threading.Event(), "cancel": threading.Event()}
    calls = []
    seen = {"n": 0}

    def fake_transcribe(engine_id, model, wav, language, options):
        calls.append(wav)
        seen["n"] += 1
        if seen["n"] == 1:
            flags["pause"].set()
        time.sleep(0.05)
        return {"text": "fake text", "language": "en"}

    monkeypatch.setattr(engines, "transcribe", fake_transcribe)
    ctx, _ = _ctx("transcribe", {"project_id": pid}, flags)
    try:
        run_transcribe(ctx)
        raised = False
    except JobPaused:
        raised = True
    assert raised
    assert len(calls) == 1
    assert db.scalar("SELECT COUNT(*) FROM records WHERE project_id=? AND status='processing'", (pid,)) == 0
    assert db.scalar("SELECT COUNT(*) FROM records WHERE project_id=? AND status='done'", (pid,)) == 1
    assert db.scalar("SELECT COUNT(*) FROM records WHERE project_id=? AND status='pending'", (pid,)) == 2

    # Resuming finishes the remaining records without touching the first one again.
    flags["pause"].clear()
    calls.clear()
    ctx2, _ = _ctx("transcribe", {"project_id": pid}, flags)
    result = run_transcribe(ctx2)
    assert result["transcribed"] == 2 and len(calls) == 2
    assert db.scalar("SELECT COUNT(*) FROM records WHERE project_id=? AND status='done'", (pid,)) == 3


def test_fatal_error_stops_job_early(client, audio_dir, monkeypatch):
    pid = _project_with_records(client, audio_dir, "fatal")
    calls = []

    def fake_transcribe(engine_id, model, wav, language, options):
        calls.append(wav)
        raise RuntimeError("openai: API key is not set. Add it under Providers.")

    monkeypatch.setattr(engines, "transcribe", fake_transcribe)
    ctx, _ = _ctx("transcribe", {"project_id": pid, "provider": "openai"})
    try:
        run_transcribe(ctx)
        raised = False
    except RuntimeError as exc:
        raised = "API key" in str(exc)
    assert raised
    # API providers run several workers, so a few records may be tried before the stop
    # signal spreads. None of them may end up failed or stuck; all stay pending for a resume.
    assert len(calls) <= 4
    assert db.scalar("SELECT COUNT(*) FROM records WHERE project_id=? AND status='failed'", (pid,)) == 0
    assert db.scalar("SELECT COUNT(*) FROM records WHERE project_id=? AND status='processing'", (pid,)) == 0
    assert db.scalar("SELECT COUNT(*) FROM records WHERE project_id=? AND status='pending'", (pid,)) == 3


def test_ordinary_failures_do_not_stop_job(client, audio_dir, monkeypatch):
    pid = _project_with_records(client, audio_dir, "flaky")

    def fake_transcribe(engine_id, model, wav, language, options):
        if "two" in str(wav):
            raise RuntimeError("decoder blew up on this file")
        return {"text": "ok", "language": "en"}

    monkeypatch.setattr(engines, "transcribe", fake_transcribe)
    ctx, _ = _ctx("transcribe", {"project_id": pid})
    result = run_transcribe(ctx)
    assert result["transcribed"] == 2 and result["failed"] == 1
    rec = db.query_one("SELECT * FROM records WHERE project_id=? AND status='failed'", (pid,))
    assert "blew up" in rec["error"] and rec["attempts"] == 1

    # Retry failed puts it back through.
    monkeypatch.setattr(engines, "transcribe", lambda *a, **k: {"text": "second try", "language": "en"})
    ctx, _ = _ctx("transcribe", {"project_id": pid, "retry_failed": True})
    result = run_transcribe(ctx)
    assert result["transcribed"] == 1
    assert db.scalar("SELECT text FROM records WHERE id=?", (rec["id"],)) == "second try"


def test_scheduled_scan_is_queued_when_due(client, audio_dir):
    pid = _project_with_records(client, audio_dir, "watched")
    db.update("projects", pid, {"watch_minutes": 5, "last_scan_at": "2020-01-01 00:00:00"})
    before = db.scalar("SELECT COUNT(*) FROM jobs WHERE type='scan' AND project_id=? AND status='queued'", (pid,))
    runner._minute_tasks()
    after = db.scalar("SELECT COUNT(*) FROM jobs WHERE type='scan' AND project_id=? AND status='queued'", (pid,))
    assert after == before + 1
    # Not queued twice while one is pending.
    runner._minute_tasks()
    assert db.scalar("SELECT COUNT(*) FROM jobs WHERE type='scan' AND project_id=? AND status='queued'", (pid,)) == after
    for j in db.query("SELECT id FROM jobs WHERE project_id=? AND status='queued'", (pid,)):
        runner.cancel(j["id"])


def test_stale_claims_are_released(client, audio_dir):
    pid = _project_with_records(client, audio_dir, "claims")
    rec = db.query_one("SELECT id FROM records WHERE project_id=?", (pid,))
    db.update("records", rec["id"], {"claimed_by": 1, "claimed_at": "2020-01-01 00:00:00"})
    runner._release_stale_claims()
    assert db.scalar("SELECT claimed_by FROM records WHERE id=?", (rec["id"],)) is None
