import json
import threading
import time

from sat import audio, db, scanner
from sat.jobs import JobContext, _claim_next, runner


def test_plan_segments_prefers_silences():
    silences = [(9.5, 10.5), (19.8, 20.4), (31.0, 31.6)]
    pieces = audio.plan_segments(40.0, silences, target=10)
    assert pieces[0] == (0.0, 10.0)
    assert pieces[1][1] == 20.1
    assert pieces[-1][1] == 40.0
    for start, end in pieces:
        assert end - start <= 15.0


def test_plan_segments_hard_cuts_without_silence():
    pieces = audio.plan_segments(35.0, [], target=10)
    assert [round(e - s, 1) for s, e in pieces] == [10.0, 10.0, 15.0]


def test_walk_audio_skips_hidden_and_non_audio(audio_dir):
    found = sorted(rel for rel, _, _ in scanner.walk_audio(audio_dir, {".wav"}))
    assert found == ["a/b/three.wav", "a/two.wav", "one.wav"]


def test_login_required(app):
    c = app.test_client()
    assert c.get("/api/projects").status_code == 401
    assert c.get("/").status_code == 302


def test_project_scan_and_records(client, audio_dir):
    r = client.post("/api/projects", json={"name": "t", "root_path": str(audio_dir), "provider": "faster_whisper", "model": "tiny", "chunk_mode": "none"})
    assert r.status_code == 200, r.get_json()
    pid = r.get_json()["id"]
    project = db.query_one("SELECT * FROM projects WHERE id=?", (pid,))
    summary = scanner.scan_project(project)
    assert summary["new"] == 3 and summary["found"] == 3
    files = client.get("/api/projects/%d/files" % pid).get_json()
    assert files["total"] == 3
    recs = client.get("/api/projects/%d/records" % pid).get_json()
    assert recs["total"] == 3
    assert all(x["status"] == "pending" for x in recs["items"])

    # Change detection: remove one file, add another, rescan.
    (audio_dir / "one.wav").unlink()
    (audio_dir / "a" / "four.wav").write_bytes((audio_dir / "a" / "two.wav").read_bytes())
    summary = scanner.scan_project(project)
    assert summary["new"] == 1 and summary["missing"] == 1
    statuses = {f["rel_path"]: f["status"] for f in client.get("/api/projects/%d/files?per_page=50" % pid).get_json()["items"]}
    assert statuses["one.wav"] == "missing" and statuses["a/four.wav"] == "ready"


def test_record_save_conflict_and_claims(client, audio_dir):
    r = client.post("/api/projects", json={"name": "c", "root_path": str(audio_dir), "chunk_mode": "none"})
    pid = r.get_json()["id"]
    scanner.scan_project(db.query_one("SELECT * FROM projects WHERE id=?", (pid,)))
    rec = client.get("/api/projects/%d/records" % pid).get_json()["items"][0]
    r = client.put("/api/records/%d" % rec["id"], json={"corrected_text": "hello", "version": rec["version"]})
    assert r.status_code == 200 and r.get_json()["version"] == rec["version"] + 1
    assert r.get_json()["review"] == "reviewed"
    stale = client.put("/api/records/%d" % rec["id"], json={"corrected_text": "old", "version": rec["version"]})
    assert stale.status_code == 409
    hist = client.get("/api/records/%d/history" % rec["id"]).get_json()["items"]
    assert hist and hist[0]["new_text"] == "hello"

    # Second user cannot claim a record the admin is editing.
    client.post("/api/users", json={"username": "bob", "password": "bobpass"})
    assert client.post("/api/records/%d/claim" % rec["id"]).status_code == 200
    other = client.application.test_client()
    other.post("/login", data={"username": "bob", "password": "bobpass"})
    assert other.post("/api/records/%d/claim" % rec["id"]).status_code == 409
    assert other.put("/api/records/%d" % rec["id"], json={"corrected_text": "x"}).status_code == 409
    client.post("/api/records/%d/release" % rec["id"])
    assert other.post("/api/records/%d/claim" % rec["id"]).status_code == 200


def test_claim_next_is_atomic(client, audio_dir):
    r = client.post("/api/projects", json={"name": "atomic", "root_path": str(audio_dir), "chunk_mode": "none"})
    pid = r.get_json()["id"]
    scanner.scan_project(db.query_one("SELECT * FROM projects WHERE id=?", (pid,)))
    total = db.scalar("SELECT COUNT(*) FROM records WHERE project_id=? AND status='pending'", (pid,))
    claimed = []
    lock = threading.Lock()

    def worker():
        while True:
            rec = _claim_next(pid)
            if rec is None:
                return
            with lock:
                claimed.append(rec["id"])
        db.close()

    threads = [threading.Thread(target=worker) for _ in range(6)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len(claimed) == total
    assert len(set(claimed)) == total


def test_job_pause_resume_cancel(client):
    jid = runner.enqueue("scan", {"project_id": 1}, project_id=1, title="x")
    assert runner.pause(jid) and db.scalar("SELECT status FROM jobs WHERE id=?", (jid,)) == "paused"
    assert runner.resume(jid) and db.scalar("SELECT status FROM jobs WHERE id=?", (jid,)) == "queued"
    assert runner.cancel(jid) and db.scalar("SELECT status FROM jobs WHERE id=?", (jid,)) == "cancelled"


def test_recover_requeues_running_jobs(client):
    jid = runner.enqueue("transcribe", {"project_id": 1}, project_id=1, title="r")
    db.update("jobs", jid, {"status": "running"})
    db.execute("UPDATE records SET status='processing' WHERE id IN (SELECT id FROM records LIMIT 1)")
    runner.recover()
    assert db.scalar("SELECT status FROM jobs WHERE id=?", (jid,)) == "queued"
    assert db.scalar("SELECT COUNT(*) FROM records WHERE status='processing'") == 0
    runner.cancel(jid)


def test_job_context_progress(client):
    jid = runner.enqueue("export", {}, title="p")
    row = db.query_one("SELECT * FROM jobs WHERE id=?", (jid,))
    ctx = JobContext(row, {"pause": threading.Event(), "cancel": threading.Event()})
    ctx.progress(done=3, total=10, message="hi", force=True)
    ctx.log("line one")
    j = client.get("/api/jobs/%d" % jid).get_json()
    assert j["done"] == 3 and j["total"] == 10 and j["message"] == "hi"
    assert client.get("/api/jobs/%d/logs" % jid).get_json()["items"][0]["message"] == "line one"


def test_import_and_export(client, audio_dir, tmp_path):
    r = client.post("/api/projects", json={"name": "imp", "root_path": str(audio_dir), "chunk_mode": "none"})
    pid = r.get_json()["id"]
    csv_path = tmp_path / "data.csv"
    csv_path.write_text("filename,transcription,correct_transcripts\na/two.wav,machine text,fixed text\nnope.wav,ghost,\n", encoding="utf-8")
    sniff = client.post("/api/import/sniff", json={"path": str(csv_path)}).get_json()
    assert sniff["guess"] == {"audio": "filename", "text": "transcription", "corrected": "correct_transcripts"}
    from sat import dataset

    jid = runner.enqueue("import", {"project_id": pid, "path": str(csv_path), "mapping": sniff["guess"], "mode": "add", "mark_reviewed": True}, project_id=pid)
    ctx = JobContext(db.query_one("SELECT * FROM jobs WHERE id=?", (jid,)), {"pause": threading.Event(), "cancel": threading.Event()})
    result = dataset.run_import(ctx)
    assert result["added"] == 2 and result["missing"] == 1
    rec = client.get("/api/projects/%d/records?q=two.wav" % pid).get_json()["items"][0]
    assert rec["text"] == "machine text" and rec["corrected_text"] == "fixed text" and rec["review"] == "reviewed"

    jid = runner.enqueue("export", {"project_id": pid, "format": "jsonl", "text_source": "best"}, project_id=pid)
    ctx = JobContext(db.query_one("SELECT * FROM jobs WHERE id=?", (jid,)), {"pause": threading.Event(), "cancel": threading.Event()})
    result = dataset.run_export(ctx)
    lines = [json.loads(l) for l in open(result["path"], encoding="utf-8")]
    assert {l["final_text"] for l in lines} == {"fixed text", "ghost"}
    assert client.get("/api/exports/" + result["download"]).status_code == 200


def test_settings_roundtrip(client):
    assert client.put("/api/settings", json={"max_parallel_jobs": "3", "auto_resume_jobs": False}).status_code == 200
    s = client.get("/api/settings").get_json()["settings"]
    assert s["max_parallel_jobs"] == 3 and s["auto_resume_jobs"] is False
    client.put("/api/settings", json={"auto_resume_jobs": True})


def test_engine_catalog_and_provider_settings(client):
    items = client.get("/api/engines").get_json()["items"]
    ids = {e["id"] for e in items}
    assert {"faster_whisper", "onnx_asr", "transformers", "indic_conformer", "openai", "deepgram", "elevenlabs", "sarvam", "openrouter", "gemini"} <= ids
    assert client.put("/api/engines/deepgram", json={"api_key": "abc123", "model": "nova-3"}).status_code == 200
    dg = [e for e in client.get("/api/engines").get_json()["items"] if e["id"] == "deepgram"][0]
    assert dg["has_key"] and dg["key_preview"].endswith("c123")
    r = client.post("/api/engines/sarvam/test", json={})
    assert r.get_json()["ok"] is False and "API key" in r.get_json()["error"]


def test_status_does_not_wait_for_a_busy_model(client, audio_dir):
    # A model load or transcription holds the engine lock; the status poll must not queue behind it.
    from sat.engines import local

    r = client.post("/api/projects", json={"name": "s", "root_path": str(audio_dir), "chunk_mode": "none"})
    pid = r.get_json()["id"]
    scanner.scan_project(db.query_one("SELECT * FROM projects WHERE id=?", (pid,)))
    rec = client.get("/api/projects/%d/records" % pid).get_json()["items"][0]
    client.post("/api/records/%d/claim" % rec["id"])
    held, release = threading.Event(), threading.Event()

    def hold():
        with local._lock:
            held.set()
            release.wait(10)

    t = threading.Thread(target=hold)
    t.start()
    held.wait(5)
    try:
        result = {}
        poll = threading.Thread(target=lambda: result.update(r=client.get("/api/status?project_id=%d" % pid)))
        poll.start()
        poll.join(3)
        assert not poll.is_alive(), "status waited for the engine lock"
        claims = result["r"].get_json()["project"]["claims"]
        assert claims == [{"id": rec["id"], "claimed_by": 1, "claimed_by_name": "Admin"}]
        started = time.time()
        local.unload_if_idle()  # returns at once instead of blocking the scheduler
        assert time.time() - started < 1
    finally:
        release.set()
        t.join()


def test_records_by_ids(client, audio_dir):
    r = client.post("/api/projects", json={"name": "ids", "root_path": str(audio_dir), "chunk_mode": "none"})
    pid = r.get_json()["id"]
    scanner.scan_project(db.query_one("SELECT * FROM projects WHERE id=?", (pid,)))
    ids = [x["id"] for x in client.get("/api/projects/%d/records" % pid).get_json()["items"]]
    data = client.get("/api/projects/%d/records?ids=%d,%d" % (pid, ids[0], ids[2])).get_json()
    assert data["total"] == 2 and sorted(x["id"] for x in data["items"]) == sorted([ids[0], ids[2]])
    assert client.get("/api/projects/%d/records?q=two" % pid).get_json()["total"] == 1


def test_default_admin_password_warning(app, caplog):
    from sat import auth

    with caplog.at_level("WARNING", logger="sat"):
        auth.warn_default_admin()
    assert "default password" in caplog.text
