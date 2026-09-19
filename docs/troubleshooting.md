# Troubleshooting

The application log is `data/logs/app.log`. Job logs are in the app under Jobs (the notebook icon on each row).

## ffmpeg was not found

The Conda environment installs ffmpeg and the app also looks for it next to the Python interpreter, so this normally means the app runs under a different Python. Either activate the environment first (`conda activate speech-annotation-tool`), install ffmpeg on the system, or enter the folder that contains `ffmpeg` and `ffprobe` under Settings > ffmpeg folder.

Files that failed because of this are flagged *error* in More > Files and are retried on the next scan.

## The app starts but nobody else can reach it

Check that `HOST` is `0.0.0.0` (the default) and that the port is open in the firewall. Windows asks once whether Python may accept connections; say yes for private networks. Reach the app with `http://<ip of the machine>:8000`.

## Login keeps expiring in Docker

Mount `./data` (the compose file does) or set `SECRET_KEY` in `.env`. Otherwise a new signing key is generated on every container recreate.

## Models download slowly or fail

Downloads come from Hugging Face. A token (Models page, admin) raises the rate limits. For gated repositories such as IndicConformer you must also accept the terms on the model page. Behind a proxy set `HTTPS_PROXY` in the environment before starting the app. A cancelled or failed download resumes where it stopped when started again.

## A job is stuck in running after a crash

It is not; start the app and the job is queued again (Settings > Resume interrupted jobs). Records that were mid-flight go back to pending. If you would rather decide yourself, turn that setting off and the job waits as *paused*.

## GPU is not used

The Models page shows what the machine offers. The app uses a GPU only when the CUDA maths libraries can be loaded, which the CPU builds of PyTorch do not include. Install the CUDA build: `pip install torch --index-url https://download.pytorch.org/whl/cu128` inside the environment. For onnx-asr add `pip install onnxruntime-gpu`. If a GPU call fails during a job the engine drops to the CPU for the rest of the session and logs a warning.

## Out of memory

Pick a smaller model, set Settings > Compute type to `int8`, lower Settings > CPU threads, and keep Parallel jobs at 1. Only one local model is in memory at a time; the Models page shows which one and lets you unload it.

## Browser does not play a file

WAV, MP3, OGG, Opus, FLAC and M4A play directly. Other formats (WMA, AIFF, AMR) are converted on the fly into `data/cache/play`; the first play of such a file takes a moment. If a record says "audio file is missing", the file was moved or deleted; a scan after putting it back sets things right.

## Chunks cut in the middle of words

Raise the target chunk length or lower the silence threshold (Settings > Silence threshold, for example `-40`) so quieter pauses count. Minimum silence of 0.3 to 0.5 seconds suits most speech. Chunk settings apply to files prepared after the change; use More > Files > Re-prepare changed files after touching the audio, or delete the records and rescan to recut everything.

## A hosted provider returns errors

The record error text contains the HTTP status and the first part of the response body. 401 or 403 means the key is wrong or lacks access; 429 means a rate limit (lower Settings > API concurrency); 413 means the audio is too big (lower the chunk length for that project). The job stops on key and URL problems so you can fix them and resume.

## Transcripts come back in the wrong language

Set the language on the project instead of leaving it blank. For Whisper, a wrong detection on very short clips is common; a language code fixes it.

## Two servers on the same port

On Windows a second `python app.py` can start on a port that is already in use. Stop the old one first (Task Manager, or `Get-Process python | Stop-Process` in PowerShell) or pass `--port`.

## Resetting everything

Stop the app and delete `data/app.db` (and `data/segments` if you want the chunks gone). Downloaded models in `data/models` can stay. The first start creates a fresh database and the admin account from `.env`.
