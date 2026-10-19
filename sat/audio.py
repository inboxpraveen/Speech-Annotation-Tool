"""Audio helpers built on ffmpeg.

Everything that touches audio goes through ffmpeg as a subprocess, so files
of any size are streamed rather than loaded into memory. Speech engines all
receive 16 kHz mono 16-bit WAV.
"""
import hashlib
import os
import re
import shutil
import subprocess
import sys
import uuid
import wave
from pathlib import Path

import numpy as np

from sat import db
from sat.config import CACHE_DIR

SAMPLE_RATE = 16000

# Formats browsers can play directly. Anything else is transcoded on demand.
BROWSER_FRIENDLY = {".wav", ".mp3", ".ogg", ".oga", ".opus", ".flac", ".m4a", ".mp4", ".webm", ".aac"}


class AudioError(Exception):
    pass


def _tool(name):
    configured = (db.get_setting("ffmpeg_path") or "").strip()
    if configured:
        base = Path(configured)
        candidate = base / name if base.is_dir() else base.parent / name
        for c in (candidate, candidate.with_suffix(".exe")):
            if c.exists():
                return str(c)
    found = shutil.which(name)
    if found:
        return found
    # A conda environment keeps ffmpeg next to its python (Library/bin on Windows).
    exe_dir = Path(sys.executable).resolve().parent
    for folder in (exe_dir, exe_dir / "Library" / "bin", exe_dir.parent / "bin"):
        for candidate in (folder / name, folder / (name + ".exe")):
            if candidate.exists():
                return str(candidate)
    raise AudioError("%s was not found. Install ffmpeg or set its folder in Settings." % name)


def ffmpeg_available():
    try:
        _tool("ffmpeg")
        _tool("ffprobe")
        return True
    except AudioError:
        return False


def ffmpeg_version():
    try:
        out = subprocess.run([_tool("ffmpeg"), "-version"], capture_output=True, text=True, timeout=20)
        first = out.stdout.splitlines()[0] if out.stdout else ""
        match = re.search(r"ffmpeg version (\S+)", first)
        return match.group(1) if match else first
    except Exception:
        return ""


def _run(cmd, timeout=None):
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, encoding="utf-8", errors="replace")
    except FileNotFoundError as exc:
        raise AudioError(str(exc))
    except subprocess.TimeoutExpired:
        raise AudioError("ffmpeg timed out")
    if proc.returncode != 0:
        tail = (proc.stderr or "").strip().splitlines()[-3:]
        raise AudioError("ffmpeg failed: " + " | ".join(tail))
    return proc


def probe_duration(path):
    """Duration in seconds, or None when ffprobe cannot tell."""
    cmd = [
        _tool("ffprobe"), "-v", "error", "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1", str(path),
    ]
    proc = _run(cmd, timeout=60)
    text = (proc.stdout or "").strip()
    try:
        return round(float(text), 3)
    except ValueError:
        return None


def to_wav16k(src, dst, start=None, end=None):
    """Convert (a slice of) any audio file to 16 kHz mono PCM WAV.

    ffmpeg writes to a temporary name that is renamed at the end, so a crash
    or a second request for the same file never sees a half written WAV.
    """
    dst = Path(dst)
    dst.parent.mkdir(parents=True, exist_ok=True)
    tmp = dst.with_name("%s.%s.tmp" % (dst.name, uuid.uuid4().hex[:8]))
    cmd = [_tool("ffmpeg"), "-hide_banner", "-loglevel", "error", "-y", "-nostdin"]
    if start is not None:
        cmd += ["-ss", "%.3f" % start]
    cmd += ["-i", str(src)]
    if end is not None and start is not None:
        cmd += ["-t", "%.3f" % max(0.0, end - start)]
    cmd += ["-vn", "-ac", "1", "-ar", str(SAMPLE_RATE), "-acodec", "pcm_s16le", "-f", "wav", str(tmp)]
    try:
        _run(cmd)
        if not tmp.exists() or tmp.stat().st_size < 100:
            raise AudioError("conversion produced no audio for %s" % src)
        os.replace(tmp, dst)
    finally:
        tmp.unlink(missing_ok=True)
    return dst


def wav_duration(path):
    with wave.open(str(path), "rb") as w:
        return w.getnframes() / float(w.getframerate())


def read_wav(path):
    """Read a 16 kHz mono PCM WAV into a float32 numpy array in [-1, 1]."""
    with wave.open(str(path), "rb") as w:
        if w.getframerate() != SAMPLE_RATE or w.getnchannels() != 1 or w.getsampwidth() != 2:
            raise AudioError("expected 16 kHz mono 16-bit WAV: %s" % path)
        frames = w.readframes(w.getnframes())
    return np.frombuffer(frames, dtype=np.int16).astype(np.float32) / 32768.0


def write_wav(path, samples):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    data = np.clip(samples * 32768.0, -32768, 32767).astype(np.int16)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SAMPLE_RATE)
        w.writeframes(data.tobytes())
    return path


_SILENCE_RE = re.compile(r"silence_(start|end): ([0-9.]+)")


def detect_silences(path, threshold_db=-35, min_silence=0.4):
    """Return [(start, end), ...] silent stretches using ffmpeg silencedetect."""
    cmd = [
        _tool("ffmpeg"), "-hide_banner", "-nostdin", "-i", str(path), "-vn",
        "-af", "silencedetect=noise=%ddB:d=%.3f" % (int(threshold_db), float(min_silence)),
        "-f", "null", "-",
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    spans, start = [], None
    for kind, value in _SILENCE_RE.findall(proc.stderr or ""):
        if kind == "start":
            start = float(value)
        elif start is not None:
            spans.append((start, float(value)))
            start = None
    return spans


def plan_segments(duration, silences, target, min_len=None, max_len=None):
    """Choose cut points so that each piece is about `target` seconds long.

    Cuts are placed in the middle of a silence close to the target length.
    Pieces never exceed max_len; if no silence is found in time we cut hard.
    """
    if duration is None or duration <= 0:
        return []
    target = float(target)
    max_len = float(max_len or target * 1.5)
    min_len = float(min_len or max(1.0, target * 0.3))
    mids = [((s + e) / 2.0, e - s) for s, e in silences]
    pieces, cursor = [], 0.0
    while duration - cursor > max_len:
        low, high = cursor + min_len, cursor + max_len
        best = None
        for mid, length in mids:
            if low <= mid <= high:
                score = abs(mid - (cursor + target)) - 0.5 * length
                if best is None or score < best[0]:
                    best = (score, mid)
        cut = best[1] if best else cursor + target
        pieces.append((cursor, cut))
        cursor = cut
    pieces.append((cursor, duration))
    return [(round(s, 3), round(e, 3)) for s, e in pieces if e - s > 0.05]


def segment_file(src, out_dir, mode, chunk_seconds, threshold_db=-35, min_silence=0.4, duration=None):
    """Split a file into 16 kHz WAV pieces. Returns [(index, start, end, path)]."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    if duration is None:
        duration = probe_duration(src)
    if duration is None:
        raise AudioError("could not read duration of %s" % src)
    chunk_seconds = float(chunk_seconds or 30)
    if mode == "fixed":
        pieces = []
        cursor = 0.0
        while cursor < duration:
            pieces.append((round(cursor, 3), round(min(duration, cursor + chunk_seconds), 3)))
            cursor += chunk_seconds
    elif mode == "silence":
        silences = detect_silences(src, threshold_db, min_silence)
        pieces = plan_segments(duration, silences, chunk_seconds)
    else:
        raise AudioError("unknown chunk mode %s" % mode)
    results = []
    for index, (start, end) in enumerate(pieces):
        target = out_dir / ("%04d.wav" % index)
        to_wav16k(src, target, start, end)
        results.append((index, start, end, target))
    return results


def split_wav_for_engine(wav_path, max_seconds, threshold_db=-35, min_silence=0.3):
    """Cut an already converted WAV into pieces no longer than max_seconds.

    Used when a provider has a hard length limit. Pieces are cut by ffmpeg so
    a two hour file never has to sit in memory. Returns a list of WAV paths
    (the original path when no split is needed).
    """
    duration = wav_duration(wav_path)
    if duration <= max_seconds:
        return [Path(wav_path)]
    silences = detect_silences(wav_path, threshold_db, min_silence)
    pieces = plan_segments(duration, silences, max_seconds * 0.8, max_len=max_seconds)
    out = []
    for i, (start, end) in enumerate(pieces):
        if end - start < 0.1:
            continue
        target = CACHE_DIR / "parts" / ("%s.part%03d.wav" % (Path(wav_path).stem, i))
        out.append(to_wav16k(wav_path, target, start, end))
    return out


def playable_path(record):
    """Path to serve for the browser, transcoding to WAV when needed."""
    src = Path(record["audio_path"])
    if src.suffix.lower() in BROWSER_FRIENDLY:
        return src, None
    key = hashlib.sha1(str(src).encode("utf-8")).hexdigest()[:20]
    dst = CACHE_DIR / "play" / ("%s.wav" % key)
    if not dst.exists() or dst.stat().st_mtime < src.stat().st_mtime:
        to_wav16k(src, dst)
    return dst, "audio/wav"


def prepared_wav(record):
    """Return a 16 kHz mono WAV for a record, converting once and caching.

    record["audio_path"] always points at exactly the audio of the record
    (segment files are cut when a project is scanned), so no slicing here.
    """
    src = Path(record["audio_path"])
    if not src.exists():
        raise AudioError("audio file is missing: %s" % src)
    if src.suffix.lower() == ".wav":
        try:
            with wave.open(str(src), "rb") as w:
                if w.getframerate() == SAMPLE_RATE and w.getnchannels() == 1 and w.getsampwidth() == 2:
                    return src, False
        except (wave.Error, EOFError):
            pass
    key = hashlib.sha1(("%s|%s" % (src, src.stat().st_mtime)).encode("utf-8")).hexdigest()[:20]
    dst = CACHE_DIR / "wav" / ("%s.wav" % key)
    if not dst.exists():
        to_wav16k(src, dst)
    return dst, True


def discard_prepared(path):
    """Remove a converted WAV once a job is done with it."""
    try:
        Path(path).unlink()
    except OSError:
        pass


def trim_play_cache(max_mb=None):
    """Keep the browser transcode cache under a size limit, oldest files first."""
    if max_mb is None:
        try:
            max_mb = float(db.get_setting("play_cache_mb") or 1000)
        except (TypeError, ValueError):
            max_mb = 1000
    folder = CACHE_DIR / "play"
    if not folder.exists():
        return
    files = []
    for p in folder.glob("*.wav"):
        try:
            st = p.stat()
            files.append((st.st_atime, st.st_size, p))
        except OSError:
            continue
    total = sum(f[1] for f in files)
    files.sort()
    while total > max_mb * 1024 * 1024 and files:
        _, size, p = files.pop(0)
        try:
            p.unlink()
            total -= size
        except OSError:
            pass
