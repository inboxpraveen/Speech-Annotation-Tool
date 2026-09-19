"""Runtime configuration.

Only the basics come from the environment (.env or real env vars). Everything
else is stored in the database and edited inside the app.
"""
import os
import secrets
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")


def _env(name, default=None):
    value = os.getenv(name)
    if value is None or value.strip() == "":
        return default
    return value.strip()


_data = Path(_env("DATA_DIR", "data")).expanduser()
DATA_DIR = (_data if _data.is_absolute() else BASE_DIR / _data).resolve()
HOST = _env("HOST", "0.0.0.0")
PORT = int(_env("PORT", "8000"))
ADMIN_USERNAME = _env("ADMIN_USERNAME", "admin")
ADMIN_PASSWORD = _env("ADMIN_PASSWORD", "admin")
LOG_LEVEL = _env("LOG_LEVEL", "INFO").upper()
# Extra folders the in-app folder browser should offer as starting points
# (comma separated). Docker uses this to expose the mounted /audio folder.
AUDIO_ROOTS = [p for p in (_env("AUDIO_ROOTS", "") or "").split(",") if p.strip()]

DB_PATH = DATA_DIR / "app.db"
LOG_DIR = DATA_DIR / "logs"
MODELS_DIR = DATA_DIR / "models"
SEGMENTS_DIR = DATA_DIR / "segments"
EXPORTS_DIR = DATA_DIR / "exports"
IMPORTS_DIR = DATA_DIR / "imports"
CACHE_DIR = DATA_DIR / "cache"

for _d in (DATA_DIR, LOG_DIR, MODELS_DIR, SEGMENTS_DIR, EXPORTS_DIR, IMPORTS_DIR, CACHE_DIR):
    _d.mkdir(parents=True, exist_ok=True)

# All model downloads (Hugging Face, faster-whisper, onnx-asr) land under the
# data folder so they survive container rebuilds. Must be set before any of
# those libraries are imported.
os.environ.setdefault("HF_HOME", str(MODELS_DIR / "huggingface"))
os.environ.setdefault("HF_HUB_DISABLE_TELEMETRY", "1")
os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")
os.environ.setdefault("HF_HUB_VERBOSITY", "error")
os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")


def _secret_key():
    value = _env("SECRET_KEY")
    if value:
        return value
    key_file = DATA_DIR / "secret_key"
    if key_file.exists():
        return key_file.read_text().strip()
    value = secrets.token_hex(32)
    key_file.write_text(value)
    return value


SECRET_KEY = _secret_key()
