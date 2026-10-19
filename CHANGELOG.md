# Changelog

## Unreleased

Fixed

- The review page no longer redraws rows on every status refresh. Audio kept stopping and the text box lost focus every two seconds. Rows a user is typing in, focused on or listening to are never redrawn; reloads after a scan or a finished job wait until the user is idle.
- The status refresh no longer waits for a local model to load or transcribe. During a first model download the app looked frozen and could run out of server threads.
- Pressing a button while a status refresh was in flight started a second refresh loop. Refreshes now run one at a time, and hidden tabs refresh every 30 seconds.
- Edit claims stay alive while the user keeps typing, so a long edit is not released after three minutes.
- A save that conflicts with someone else's edit keeps the text the user typed.
- Select all no longer discards unsaved text.
- Selected and claimed rows are highlighted again.
- A transcription job says when it is downloading a model for the first time.
- The models page no longer clears a typed model id while a download runs.
- The projects and jobs pages refresh once more when a job ends, so finished jobs do not look stuck.
- Converted audio is written under a temporary name and renamed, so an interrupted conversion never leaves a broken file in the cache.

Changed

- Layout works on phones and tablets: records stack into one block each below 992 px, wide tables scroll inside their card, and the notifications menu stays on screen.
- Faster on big projects: indexes for the project stats and edit claims, record counts skip the files table unless searching, and the review page refreshes visible rows by id. On a 500,000 record project a status refresh went from about 500 ms to 50 ms.
- Project and dashboard pages no longer import torch or run ffmpeg on every load. The first page after a start took about 5 seconds.

## 3.0.0 (2026-09-19)

Complete rewrite. Projects and data from 2.x are not migrated automatically, but the old `transcriptions.csv` imports as it is (More > Import data).

Added

- Projects that track a folder recursively, with change detection (new, changed, missing files) and optional scheduled rescans.
- Silence based and fixed length chunking through ffmpeg.
- Local engines: faster-whisper, onnx-asr (Parakeet, Canary), Hugging Face transformers, AI4Bharat IndicConformer, Qwen3-ASR.
- Hosted providers: OpenAI, Groq, Deepgram, ElevenLabs, Sarvam, AssemblyAI, Google Gemini, Mistral, OpenRouter, custom OpenAI compatible servers.
- Model management in the app: catalog, downloads with progress, cache view, unload, custom repo ids, Hugging Face token.
- Job system with pause, resume, stop, per record checkpoints, crash recovery and logs.
- Multi-user accounts, presence, edit claims, version checks and edit history.
- In-app notifications and a live status bar.
- Import from CSV, TSV, XLSX, JSON and JSONL; export to CSV, XLSX, JSONL and Hugging Face audio folders.
- Docker image and compose files (CPU by default, GPU override), Conda environment with ffmpeg included.
- Test suite.

Changed

- Storage moved from CSV files to SQLite.
- Server is waitress instead of the Flask development server.
- Bootstrap is served locally; the app works without internet access.
- Configuration moved out of environment variables into the app; `.env` keeps only host, port, data folder and the first admin.

Removed

- Native file dialog through tkinter (did not work in Docker or on a server). Replaced with a folder browser in the app.
- `PROJECT_DOCUMENTATION.md` and `QUICK_START.md`, folded into `docs/`.

Versions used while testing: Python 3.12, Flask 3.1.3, waitress 3.0.2, faster-whisper 1.2.1, ctranslate2 4.8.2, onnx-asr 0.12.0, onnxruntime 1.30.0, transformers 5.17.0, torch 2.14.0 (CPU), huggingface_hub 1.32.0, ffmpeg 9.0.1.

## 2.0.0 (2025-12-07)

Background jobs with progress, row locking, Bootstrap 5 interface, CSV storage. See the git history for details.

## 1.0.0 (2023)

First release: Whisper transcription of a folder and a simple correction table.
