# Setup

Two ways to run the tool: a Conda environment on the machine itself, or Docker. Both give you the same app on http://localhost:8000.

## Conda (Windows, Linux, macOS)

1. Install [Miniconda](https://www.anaconda.com/download) if you do not have it.
2. Clone the repository and create the environment. This installs Python 3.12, ffmpeg, CPU builds of PyTorch and every speech library the app can use. Expect 2 to 3 GB and a few minutes.

   ```bash
   git clone https://github.com/inboxpraveen/Speech-Annotation-Tool.git
   cd Speech-Annotation-Tool
   conda env create -f environment.yml
   conda activate speech-annotation-tool
   ```

3. Start the server:

   ```bash
   python app.py
   ```

   Options: `--port 9000`, `--host 127.0.0.1` (only this machine), `--threads 32`, `--dev` (Flask debug server).

4. Open http://localhost:8000. The first admin account is `admin` / `admin` unless you changed it in `.env`.

Other people on your network reach the app at `http://<your ip>:8000`. The app serves plain HTTP and has no login rate limiting, so keep it on a trusted network or read [Running it for a team](#running-it-for-a-team) first.

To update later: `git pull`, then `conda env update -f environment.yml --prune`.

## Docker

Requires Docker Desktop (Windows, macOS) or Docker Engine with the compose plugin (Linux).

```bash
git clone https://github.com/inboxpraveen/Speech-Annotation-Tool.git
cd Speech-Annotation-Tool
cp .env.example .env
```

Edit `.env` and set `AUDIO_DIR` to the host folder that holds your audio. Examples:

```
AUDIO_DIR=C:\recordings          # Windows
AUDIO_DIR=/srv/audio             # Linux
AUDIO_DIR=/Users/me/recordings   # macOS
```

Then:

```bash
docker compose up -d --build
```

Inside the container your folder is `/audio`, and the folder browser offers it as a starting point. `./data` on the host holds the database, downloaded models, segments, exports and logs. Change `PORT` in `.env` to publish the app on another port.

Without compose:

```bash
docker build -t speech-annotation-tool .
docker run -d --name speech-annotation-tool -p 8000:8000 \
  -v "$(pwd)/data:/app/data" -v "C:\recordings:/audio" speech-annotation-tool
```

`SECRET_KEY` signs login cookies. When it is blank the app generates one and stores it in the data folder, so sessions survive container recreation as long as `./data` is mounted.

### NVIDIA GPU in Docker

Install the NVIDIA Container Toolkit on the host, then build with the CUDA variant of PyTorch:

```bash
docker compose -f docker-compose.yml -f docker-compose.gpu.yml up -d --build
```

The image grows by several GB. faster-whisper and transformers use the GPU. onnx-asr (Parakeet, Canary) stays on the CPU unless you also add `onnx-asr[gpu]` to `requirements.txt` before building.

## GPU without Docker

The default environment installs CPU builds, which run everywhere. If you have an NVIDIA GPU:

```bash
conda activate speech-annotation-tool
pip install torch --index-url https://download.pytorch.org/whl/cu128
```

That one package brings the CUDA libraries that both transformers and faster-whisper need. Restart the app; the Models page shows the GPU name when it is usable. For onnx-asr on the GPU run `pip install onnxruntime-gpu` as well.

The app checks that the CUDA maths libraries can actually be loaded before it uses a GPU. When they cannot, or a GPU call fails mid-job, it switches that engine to the CPU and carries on. Force the CPU at any time under Settings > Local device.

## Running it for a team

The app is built for a team on a trusted network. Before you share it:

1. **Change the admin password.** The first account is `admin` / `admin`. Set `ADMIN_USERNAME` and `ADMIN_PASSWORD` in `.env` before the first start, or change the password from the user menu. The app logs a warning at every start while the default is still in use.
2. **Put HTTPS in front of it.** The app itself serves plain HTTP. Listen on the local machine only (`HOST=127.0.0.1`, or with Docker change the `ports` line in `docker-compose.yml` to `127.0.0.1:8000:8000`), let a reverse proxy terminate TLS, and set `COOKIE_SECURE=true` so the login cookie is only sent over HTTPS. With Caddy:

   ```
   annotate.example.com {
       reverse_proxy 127.0.0.1:8000
   }
   ```

   With nginx, allow large uploads and long requests:

   ```
   location / {
       proxy_pass http://127.0.0.1:8000;
       proxy_set_header Host $host;
       client_max_body_size 2g;
       proxy_read_timeout 600s;
   }
   ```

   There is no login rate limiting in the app. If it is reachable from outside your network, add a limit at the proxy.
3. **Know who can see what.** Every signed-in user can browse the folders the server account can read and can create projects on them. In Docker the host files it can reach are limited to the folders you mount. Provider API keys and the Hugging Face token are stored as plain text in `data/app.db`, so keep `data/` readable only by the account that runs the app.
4. **Back up the database.** This copies `data/app.db` safely while the app is running:

   ```bash
   python -c "import sqlite3; s = sqlite3.connect('data/app.db'); d = sqlite3.connect('app-backup.db'); s.backup(d)"
   ```

   Back up `data/segments` too if you cut long recordings into chunks. Models can be downloaded again.
5. **Keep it running.** The compose file already uses `restart: unless-stopped`. Without Docker, run `python app.py` from a service manager. A systemd unit on Linux (adjust the paths and user):

   ```
   [Unit]
   Description=Speech Annotation Tool
   After=network.target

   [Service]
   User=annotate
   WorkingDirectory=/opt/Speech-Annotation-Tool
   ExecStart=/opt/conda/envs/speech-annotation-tool/bin/python app.py
   Restart=on-failure

   [Install]
   WantedBy=multi-user.target
   ```

The process is a single Python server with one SQLite database. That is deliberate: there is nothing else to run, monitor or patch. If you need several servers behind a load balancer, this tool is not the right fit.

## Environment variables

Only the basics live in `.env` (or real environment variables). Everything else is edited inside the app under Settings, Providers and Models.

| Variable | Default | Meaning |
|---|---|---|
| `HOST` | `0.0.0.0` | Address to listen on. `127.0.0.1` restricts the app to this machine. |
| `PORT` | `8000` | Port. With Docker this is the host port; the container always listens on 8000. |
| `DATA_DIR` | `./data` | Database, models, segments, exports, logs. Relative paths are resolved against the repository folder. |
| `ADMIN_USERNAME` | `admin` | First admin account, created on the very first start only. |
| `ADMIN_PASSWORD` | `admin` | Password for that account. Change it in the app afterwards. |
| `SECRET_KEY` | generated | Cookie signing key. |
| `COOKIE_SECURE` | off | Set to `true` when the app is served over HTTPS, so the login cookie is never sent over plain HTTP. |
| `AUDIO_ROOTS` | empty | Extra folders the folder browser offers first, comma separated. Docker sets this to `/audio`. |
| `LOG_LEVEL` | `INFO` | Log verbosity for `data/logs/app.log`. |

## What gets stored where

```
data/
  app.db              SQLite database: users, projects, files, records, jobs, settings
  models/huggingface  downloaded models (Hugging Face cache layout)
  segments/           audio chunks cut from long recordings, per project and file
  cache/              converted 16 kHz audio and browser transcodes, trimmed automatically
  exports/            exported datasets
  imports/            files uploaded through the import dialog
  logs/app.log        rotating application log
```

Back up `data/app.db` (and `data/segments` if you chunk) to keep your work. Models can always be downloaded again.

## Hardware notes

- CPU only: Whisper `base` or `small` with int8 (the default compute type) transcribes a few times faster than real time on a modern laptop. Parakeet TDT v3 int8 is also quick on a CPU.
- RAM: 4 GB is enough for small models; `large-v3` wants 6 to 8 GB. Only one local model is loaded at a time and it is unloaded after 20 idle minutes (Settings).
- Disk: models range from 75 MB (`tiny`) to 3 GB (`large-v3`). Segments are 16 kHz mono WAV, about 2 MB per minute of audio.
- Weak machines: lower **CPU threads** and keep **Parallel jobs** at 1 under Settings.
