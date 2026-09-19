# Changelog

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
