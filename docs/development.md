# Development

## Layout

```
app.py                   entry point (waitress server, --dev for Flask debug)
sat/
  config.py              .env handling, folders, HF cache location
  db.py                  SQLite schema, connections, transactions, settings
  auth.py                users, passwords, sessions, presence
  audio.py               ffmpeg helpers: probe, convert, silence detection, chunking
  scanner.py             folder walk, change detection, record preparation
  jobs.py                job runner, scheduler, recovery, transcribe/scan/download handlers
  dataset.py             import and export
  notify.py              in-app notifications
  engines/
    __init__.py          catalog of engines and models, transcribe() entry point
    local.py             faster-whisper, onnx-asr, transformers, IndicConformer, Qwen3-ASR
    api.py               OpenAI, Groq, Deepgram, ElevenLabs, Sarvam, AssemblyAI, Gemini, Mistral, OpenRouter, custom
  routes/
    pages.py             HTML pages
    api.py               JSON API
templates/               Jinja pages (one per screen)
static/js                one script per page plus app.js (polling, toasts, folder picker)
static/vendor            Bootstrap and Bootstrap Icons, served locally
static/sample/sample.wav clip used by the Test buttons
tests/                   pytest suite
docs/                    this documentation and screenshots
```

## Running from source

```bash
conda activate speech-annotation-tool
python app.py --dev          # Flask debug server, no reloader
pytest -q                    # tests use a temporary DATA_DIR and never download models
```

Tests cover the database layer, scanning and change detection, atomic record claims across threads, pause and resume, fatal error handling, scheduled scans, import and export, the review API with version conflicts and edit claims, settings and the engine catalog.

## How work flows

1. A **scan** job walks the folder (`scanner.walk_audio`, streaming `os.scandir`), upserts `files`, then prepares each new file: probe the duration and either link one record to the original file or cut chunks with ffmpeg into `data/segments`.
2. A **transcribe** job claims records one at a time with `UPDATE ... RETURNING` (`jobs._claim_next`), converts the audio to 16 kHz WAV if needed, calls `engines.transcribe`, and writes the result back. Each record is its own checkpoint. Hosted providers use a thread pool; local engines run one at a time.
3. The scheduler thread (`JobRunner._loop`) starts queued jobs within the parallelism limit, allows only one job that holds a local model, and once a minute runs housekeeping: idle model unload, stale claim release, scheduled rescans, cache trimming.
4. On startup `JobRunner.recover` re-queues jobs that were running and resets records that were processing.

Engines return `{"text": ..., "language": ...}`. `engines.transcribe` splits audio for engines with `max_seconds` and joins the pieces. Local engines cache one loaded model in `engines.local._cache`; a GPU failure marks the engine as CPU-only for the session.

## Adding a provider

1. Write a function in `sat/engines/api.py` with the signature `fn(model, wav_path, language, options)` returning the dict above. Use `setting(provider, "api_key")` and `setting(provider, "base_url", default)` for credentials and `_post_with_retry` for the request.
2. Register it in `RUNNERS`.
3. Add a catalog entry in `sat/engines/__init__.py` with `kind: "api"`, the default model, `max_seconds` if the service limits duration, and any `options` fields (they render on the Providers page and in project settings automatically).

Local engines follow the same pattern in `sat/engines/local.py`: a loader in `_LOADERS`, a runner in `_RUNNERS`, and `repo_for` so downloads and the Models page know which Hugging Face repo and files are involved.

## API

All endpoints live under `/api` and return JSON. A session cookie from `/login` is required; the browser handles this, scripts can post the login form once.

| Method and path | Purpose |
|---|---|
| `GET /api/status?project_id=&page=&record_id=` | Poll: active jobs, unread notifications, online users, project counters. Also records presence. |
| `GET/POST /api/projects`, `GET/PUT/DELETE /api/projects/<id>` | Projects |
| `POST /api/projects/<id>/scan` `{transcribe_after, reprepare}` | Queue a scan |
| `POST /api/projects/<id>/transcribe` `{record_ids, retry_failed, provider, model, language}` | Queue transcription |
| `GET /api/projects/<id>/records?page=&per_page=&status=&review=&q=&sort=&edited=&ids=` | Paged records. `ids` (comma separated) limits the list to those records; the review page uses it to refresh the rows on screen. |
| `GET/PUT /api/records/<id>` | Read or save a record (`corrected_text`, `review`, `notes`, `status`, `version`) |
| `POST /api/records/<id>/claim`, `/release` | Edit claims |
| `GET /api/records/<id>/history`, `GET /api/records/<id>/audio` | History, audio stream (supports range requests) |
| `POST /api/projects/<id>/records/bulk` `{ids, action}` | approve, reject, reset_review, reset, skip, delete |
| `GET /api/projects/<id>/files?page=&status=&q=` | Files |
| `POST /api/projects/<id>/import`, `POST /api/import/upload`, `POST /api/import/sniff` | Import |
| `POST /api/projects/<id>/export`, `GET /api/exports`, `GET/DELETE /api/exports/<name>` | Export |
| `GET /api/jobs`, `GET /api/jobs/<id>`, `GET /api/jobs/<id>/logs?after=` | Jobs |
| `POST /api/jobs/<id>/pause`, `/resume`, `/cancel`, `DELETE /api/jobs/<id>`, `POST /api/jobs/clear` | Job control |
| `GET /api/engines`, `PUT /api/engines/<id>`, `POST /api/engines/<id>/test`, `GET /api/engines/openrouter/models` | Engines and providers |
| `GET /api/models`, `POST /api/models/download`, `/delete`, `/unload` | Local models |
| `GET /api/users`, `POST /api/users`, `PUT/DELETE /api/users/<id>`, `POST /api/me/password` | Accounts |
| `GET/PUT /api/settings` | Settings (admin) |
| `GET /api/fs/list?path=&ext=` | Folder browser |
| `GET /api/notifications`, `POST /api/notifications/read` | Notifications |

Errors come back as `{"error": "..."}` with a 4xx or 5xx status. Saving a record whose version changed returns 409 with the fresh record in `record`.

## Database

SQLite at `data/app.db`, WAL mode, one connection per thread, one process-wide write lock. Tables: `users`, `settings`, `projects`, `files`, `records`, `record_history`, `jobs`, `job_logs`, `notifications`. Timestamps are UTC in `YYYY-MM-DD HH:MM:SS` form so they compare with SQLite's `datetime('now')`.

## Style

Plain Python, no framework magic, comments where the intent is not obvious from the code. Keep functions short and the tree flat. Run `pyflakes sat` before sending changes.
