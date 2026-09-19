import os
import sys
import tempfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

_tmp = tempfile.mkdtemp(prefix="sat-test-")
os.environ["DATA_DIR"] = _tmp
os.environ["ADMIN_USERNAME"] = "admin"
os.environ["ADMIN_PASSWORD"] = "admin"


@pytest.fixture(scope="session")
def app():
    from sat import create_app

    application = create_app(start_jobs=False)
    application.config["TESTING"] = True
    return application


@pytest.fixture()
def client(app):
    c = app.test_client()
    c.post("/login", data={"username": "admin", "password": "admin"})
    return c


@pytest.fixture()
def audio_dir(tmp_path):
    """A folder with tiny generated WAV files (silence) in nested folders."""
    import numpy as np

    from sat import audio

    (tmp_path / "a" / "b").mkdir(parents=True)
    (tmp_path / ".hidden").mkdir()
    tone = np.sin(np.linspace(0, 2 * np.pi * 440 * 2, audio.SAMPLE_RATE * 2)).astype("float32") * 0.3
    audio.write_wav(tmp_path / "one.wav", tone)
    audio.write_wav(tmp_path / "a" / "two.wav", tone)
    audio.write_wav(tmp_path / "a" / "b" / "three.wav", tone)
    audio.write_wav(tmp_path / ".hidden" / "skip.wav", tone)
    (tmp_path / "notes.txt").write_text("not audio")
    return tmp_path
