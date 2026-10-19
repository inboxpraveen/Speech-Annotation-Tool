"""Local speech engines.

Four engine families cover the popular open models:

* faster_whisper  - Whisper family through CTranslate2 (fast on CPU with int8)
* onnx_asr        - NVIDIA Parakeet / Canary and others through onnxruntime
* transformers    - any Hugging Face model the ASR pipeline understands
* indic_conformer - AI4Bharat IndicConformer (22 Indian languages)
* qwen_asr        - Qwen3-ASR through the qwen-asr package (optional install)

Only one local model is held in memory at a time. It is unloaded after a
period of inactivity (see Settings) so the machine gets its RAM back.
"""
import fnmatch
import gc
import importlib
import importlib.util
import logging
import threading
import time
from pathlib import Path

from sat import audio, db
from sat.config import MODELS_DIR

log = logging.getLogger("sat.engines.local")

_cache = {"key": None, "obj": None, "last_used": 0.0, "extra": {}}
_lock = threading.RLock()
_gpu_broken = set()


def module_available(name):
    try:
        return importlib.util.find_spec(name) is not None
    except (ValueError, ImportError):
        return False


def hf_token():
    return (db.get_setting("hf_token") or "").strip() or None


def torch_cuda():
    try:
        import torch
        return bool(torch.cuda.is_available())
    except Exception:
        return False


def cuda_runtime_present():
    """True when the CUDA maths libraries CTranslate2 needs can actually be loaded.

    ctranslate2 reports a GPU as soon as a driver exists, but without cuBLAS
    and cuDNN the first call fails or hangs. A CUDA build of torch ships
    those libraries, so import it first, then try to load cuBLAS by name.
    """
    import ctypes
    import ctypes.util
    try:
        importlib.import_module("torch")  # adds its lib folder to the DLL search path
    except Exception:
        pass
    names = ["cublas64_13", "cublas64_12", "cublas", "libcublas.so.13", "libcublas.so.12"]
    for name in names:
        try:
            found = ctypes.util.find_library(name)
            ctypes.CDLL(found or name)
            return True
        except OSError:
            continue
    return False


def ctranslate2_cuda():
    try:
        import ctranslate2
        return ctranslate2.get_cuda_device_count() > 0 and cuda_runtime_present()
    except Exception:
        return False


def onnx_cuda():
    try:
        import onnxruntime
        return "CUDAExecutionProvider" in onnxruntime.get_available_providers()
    except Exception:
        return False


def device_for(engine):
    """Resolve the Settings device preference for a given engine family."""
    pref = (db.get_setting("local_device") or "auto").lower()
    if pref == "cpu" or engine in _gpu_broken:
        return "cpu"
    if engine == "faster_whisper":
        return "cuda" if ctranslate2_cuda() else "cpu"
    if engine == "onnx_asr":
        return "cuda" if onnx_cuda() else "cpu"
    return "cuda" if torch_cuda() else "cpu"


def compute_type_for(device):
    pref = (db.get_setting("compute_type") or "auto").lower()
    if pref != "auto":
        return pref
    return "float16" if device == "cuda" else "int8"


def cpu_threads():
    try:
        return int(db.get_setting("cpu_threads") or 0)
    except (TypeError, ValueError):
        return 0


def installed():
    """Which local engines can be imported. Cheap enough for every page load."""
    hf = module_available("transformers") and module_available("torch")
    return {
        "faster_whisper": module_available("faster_whisper"),
        "onnx_asr": module_available("onnx_asr"),
        "transformers": hf,
        "indic_conformer": hf,
        "qwen_asr": module_available("qwen_asr"),
    }


def capabilities():
    """What is installed and which accelerators are visible. Shown on the Models page."""
    caps = installed()
    caps.update({
        "torch_cuda": torch_cuda(),
        "ctranslate2_cuda": ctranslate2_cuda(),
        "onnx_cuda": onnx_cuda(),
        "ffmpeg": audio.ffmpeg_available(),
        "ffmpeg_version": audio.ffmpeg_version(),
    })
    try:
        import torch
        caps["torch_version"] = torch.__version__
        if caps["torch_cuda"]:
            caps["gpu_name"] = torch.cuda.get_device_name(0)
    except Exception:
        pass
    return caps


# Loading ---------------------------------------------------------------------

def loaded_model():
    # No lock here: the status poll calls this, and _lock is held for the whole
    # of a model load or download and every transcription.
    key, last_used = _cache["key"], _cache["last_used"]
    if key is None:
        return None
    engine, model, device, extra = key
    return {"engine": engine, "model": model, "device": device, "idle_seconds": int(time.time() - last_used)}


def unload():
    with _lock:
        if _cache["obj"] is None:
            return
        key = _cache["key"]
        _cache.update({"key": None, "obj": None, "extra": {}})
        gc.collect()
        try:
            import torch
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
        except Exception:
            pass
        log.info("unloaded local model %s", key)


def unload_if_idle():
    minutes = db.get_setting("unload_idle_minutes")
    try:
        minutes = float(minutes)
    except (TypeError, ValueError):
        minutes = 0
    if minutes <= 0:
        return
    # A held lock means a model is loading or transcribing, so it is not idle.
    # Waiting for it would stall the scheduler loop.
    if not _lock.acquire(blocking=False):
        return
    try:
        if _cache["obj"] is not None and time.time() - _cache["last_used"] > minutes * 60:
            unload()
    finally:
        _lock.release()


def get_model(engine, model, options=None):
    options = options or {}
    device = device_for(engine)
    extra = _extra_key(engine, device, options)
    key = (engine, model, device, extra)
    with _lock:
        if _cache["key"] == key and _cache["obj"] is not None:
            _cache["last_used"] = time.time()
            return _cache["obj"], device
        unload()
        started = time.time()
        loader = _LOADERS[engine]
        obj = loader(model, device, options)
        _cache.update({"key": key, "obj": obj, "last_used": time.time()})
        log.info("loaded %s model %s on %s in %.1fs", engine, model, device, time.time() - started)
        return obj, device


def _extra_key(engine, device, options):
    """Part of the cache key that changes how a model is loaded."""
    if engine == "faster_whisper":
        return options.get("compute_type") or compute_type_for(device)
    if engine == "onnx_asr":
        return _onnx_quant(device, options)
    return ""


def _onnx_quant(device, options):
    q = (options.get("quantization") or db.get_setting("engine.onnx_asr.quantization") or "auto")
    if q == "auto":
        return "int8" if device == "cpu" else "none"
    return q


def _load_faster_whisper(model, device, options):
    from faster_whisper import WhisperModel

    kwargs = {"device": device, "compute_type": options.get("compute_type") or compute_type_for(device)}
    threads = cpu_threads()
    if threads > 0:
        kwargs["cpu_threads"] = threads
    token = hf_token()
    if token:
        kwargs["use_auth_token"] = token
    return WhisperModel(model, **kwargs)


def _load_onnx_asr(model, device, options):
    import onnx_asr

    quant = _onnx_quant(device, options)
    kwargs = {}
    if quant and quant != "none":
        kwargs["quantization"] = quant
    if device == "cuda":
        kwargs["providers"] = ["CUDAExecutionProvider", "CPUExecutionProvider"]
    else:
        kwargs["providers"] = ["CPUExecutionProvider"]
        threads = cpu_threads()
        if threads > 0:
            import onnxruntime as rt
            so = rt.SessionOptions()
            so.intra_op_num_threads = threads
            kwargs["sess_options"] = so
    asr = onnx_asr.load_model(model, **kwargs)
    vad = onnx_asr.load_vad("silero", providers=["CPUExecutionProvider"])
    return {"asr": asr, "vad": vad, "model": model}


def _load_transformers(model, device, options):
    import torch
    from transformers import pipeline

    dtype = torch.float16 if device == "cuda" else torch.float32
    kwargs = {"model": model, "device": 0 if device == "cuda" else -1, "token": hf_token()}
    try:
        pipe = pipeline("automatic-speech-recognition", dtype=dtype, trust_remote_code=bool(options.get("trust_remote_code")), **kwargs)
    except TypeError:
        pipe = pipeline("automatic-speech-recognition", torch_dtype=dtype, trust_remote_code=bool(options.get("trust_remote_code")), **kwargs)
    return pipe


def _load_indic_conformer(model, device, options):
    from transformers import AutoModel

    m = AutoModel.from_pretrained(model, trust_remote_code=True, token=hf_token())
    try:
        m = m.to(device)
    except Exception:
        pass
    try:
        m.eval()
    except Exception:
        pass
    return m


def _load_qwen_asr(model, device, options):
    import torch
    from qwen_asr import Qwen3ASRModel

    kwargs = {"dtype": torch.bfloat16 if device == "cuda" else torch.float32, "device_map": "cuda:0" if device == "cuda" else "cpu"}
    return Qwen3ASRModel.from_pretrained(model, **kwargs)


_LOADERS = {
    "faster_whisper": _load_faster_whisper,
    "onnx_asr": _load_onnx_asr,
    "transformers": _load_transformers,
    "indic_conformer": _load_indic_conformer,
    "qwen_asr": _load_qwen_asr,
}


# Inference -------------------------------------------------------------------

def transcribe(engine, model, wav_path, language=None, options=None):
    """Return {"text": ..., "language": ...} for a 16 kHz mono WAV file.

    If the GPU turns out to be unusable (missing CUDA libraries and the
    like) the engine falls back to the CPU for the rest of the session.
    """
    options = options or {}
    with _lock:
        obj, device = get_model(engine, model, options)
        _cache["last_used"] = time.time()
        fn = _RUNNERS[engine]
        try:
            result = fn(obj, model, str(wav_path), language, options, device)
        except Exception as exc:
            text = str(exc).lower()
            if device == "cuda" and any(m in text for m in ("cuda", "cublas", "cudnn", "gpu", "device")):
                log.warning("%s failed on the GPU (%s); using the CPU from now on", engine, exc)
                _gpu_broken.add(engine)
                unload()
                obj, device = get_model(engine, model, options)
                result = fn(obj, model, str(wav_path), language, options, device)
            else:
                raise
        _cache["last_used"] = time.time()
        return result


def _run_faster_whisper(m, model, wav_path, language, options, device):
    kwargs = {
        "language": language or None,
        "beam_size": int(options.get("beam_size") or 5),
        "vad_filter": options.get("vad_filter", True) not in (False, "false", "0", 0),
        "task": options.get("task") or "transcribe",
        "condition_on_previous_text": False,
    }
    if options.get("initial_prompt"):
        kwargs["initial_prompt"] = options["initial_prompt"]
    segments, info = m.transcribe(wav_path, **kwargs)
    text = " ".join(s.text.strip() for s in segments if s.text and s.text.strip())
    return {"text": text.strip(), "language": getattr(info, "language", None)}


def _run_onnx_asr(bundle, model, wav_path, language, options, device):
    asr = bundle["asr"]
    kwargs = {}
    name = model.lower()
    if language and ("canary" in name or "whisper" in name):
        kwargs["language"] = language
    duration = audio.wav_duration(wav_path)
    if duration > 25:
        results = asr.with_vad(bundle["vad"]).recognize(wav_path, **kwargs)
        text = " ".join(r.text.strip() for r in results if getattr(r, "text", "").strip())
    else:
        text = asr.recognize(wav_path, **kwargs)
        if not isinstance(text, str):
            text = " ".join(r.text for r in text)
    return {"text": text.strip(), "language": language or None}


def _run_transformers(pipe, model, wav_path, language, options, device):
    samples = audio.read_wav(wav_path)
    payload = {"raw": samples, "sampling_rate": audio.SAMPLE_RATE}
    kwargs = {}
    model_type = getattr(getattr(pipe, "model", None), "config", None)
    model_type = getattr(model_type, "model_type", "") or ""
    if model_type == "whisper":
        gen = {"task": options.get("task") or "transcribe"}
        if language:
            gen["language"] = language
        kwargs["generate_kwargs"] = gen
    if len(samples) > audio.SAMPLE_RATE * 30:
        kwargs["chunk_length_s"] = 30
    try:
        out = pipe(payload, **kwargs)
    except TypeError:
        kwargs.pop("chunk_length_s", None)
        out = pipe(payload, **kwargs)
    text = out.get("text", "") if isinstance(out, dict) else str(out)
    return {"text": text.strip(), "language": language or None}


def _run_indic_conformer(m, model, wav_path, language, options, device):
    import torch

    samples = audio.read_wav(wav_path)
    wav = torch.from_numpy(samples).unsqueeze(0)
    try:
        wav = wav.to(device)
    except Exception:
        pass
    lang = (language or options.get("language") or "hi").split("-")[0].lower()
    decoding = options.get("decoding") or "rnnt"
    with torch.no_grad():
        text = m(wav, lang, decoding)
    if isinstance(text, (list, tuple)):
        text = " ".join(str(t) for t in text)
    return {"text": str(text).strip(), "language": lang}


def _run_qwen_asr(m, model, wav_path, language, options, device):
    results = m.transcribe(audio=wav_path, language=language or None)
    first = results[0] if results else None
    return {"text": (getattr(first, "text", "") or "").strip(), "language": getattr(first, "language", None) or language}


_RUNNERS = {
    "faster_whisper": _run_faster_whisper,
    "onnx_asr": _run_onnx_asr,
    "transformers": _run_transformers,
    "indic_conformer": _run_indic_conformer,
    "qwen_asr": _run_qwen_asr,
}


# Downloads and the local cache ------------------------------------------------

def repo_for(engine, model, options=None):
    """Hugging Face repo id and allow-patterns used when downloading a model."""
    options = options or {}
    if engine == "faster_whisper":
        from faster_whisper.utils import _MODELS
        repo = model if "/" in model else _MODELS.get(model)
        if repo is None:
            raise ValueError("unknown faster-whisper model %s" % model)
        return repo, ["config.json", "preprocessor_config.json", "model.bin", "tokenizer.json", "vocabulary.*"]
    if engine == "onnx_asr":
        from onnx_asr.resolver import model_repos
        repo = model if "/" in model else model_repos.get(model)
        if repo is None:
            raise ValueError("unknown onnx-asr model %s" % model)
        quant = _onnx_quant(device_for(engine), options)
        if quant and quant != "none":
            patterns = ["config.json", "config.yaml", "vocab*", "*.%s.onnx" % quant, "*.%s.onnx.data" % quant, "*.%s.onnx?data" % quant]
        else:
            patterns = ["config.json", "config.yaml", "vocab*", "*[!8].onnx", "*[!8].onnx.data"]
        return repo, patterns
    if engine in ("transformers", "qwen_asr"):
        return model, ["*.json", "*.txt", "*.model", "*.py", "*.safetensors", "*.tiktoken", "*.jinja", "*.yaml", "*.yml", "*.md"]
    if engine == "indic_conformer":
        return model, None
    raise ValueError("unknown engine %s" % engine)


def expected_size(repo, patterns):
    """Bytes that a download will fetch, or None when the hub does not say."""
    try:
        from huggingface_hub import HfApi
        info = HfApi(token=hf_token()).model_info(repo, files_metadata=True)
    except Exception:
        return None
    total = 0
    for s in info.siblings or []:
        if patterns and not any(fnmatch.fnmatch(s.rfilename, p) for p in patterns):
            continue
        total += s.size or 0
    return total or None


def cache_dir_for(repo):
    hub = Path(MODELS_DIR) / "huggingface" / "hub"
    return hub / ("models--" + repo.replace("/", "--"))


def dir_size(path):
    total = 0
    path = Path(path)
    if not path.exists():
        return 0
    for p in path.rglob("*"):
        try:
            if p.is_file():
                total += p.stat().st_size
        except OSError:
            pass
    return total


def is_downloaded(engine, model, options=None):
    try:
        repo, patterns = repo_for(engine, model, options)
    except Exception:
        return False
    snap = cache_dir_for(repo) / "snapshots"
    if not snap.exists():
        return False
    return any(p.is_file() and p.suffix not in (".md", ".txt", ".json") for p in snap.rglob("*"))


def download(engine, model, options=None, progress=None, stop=None):
    """Fetch a model into the local cache, reporting byte progress."""
    from huggingface_hub import snapshot_download

    repo, patterns = repo_for(engine, model, options)
    total = expected_size(repo, patterns)
    target = cache_dir_for(repo)
    error = {}

    def worker():
        try:
            kwargs = {"repo_id": repo, "token": hf_token()}
            if patterns:
                kwargs["allow_patterns"] = patterns
            snapshot_download(**kwargs)
        except Exception as exc:
            error["exc"] = exc

    t = threading.Thread(target=worker, daemon=True)
    t.start()
    while t.is_alive():
        t.join(1.0)
        if progress:
            progress(dir_size(target), total)
        if stop and stop():
            raise RuntimeError("download stopped")
    if "exc" in error:
        raise error["exc"]
    if progress:
        progress(dir_size(target), total)
    return repo


def cached_repos():
    """Repos in the local cache with sizes, for the Models page."""
    try:
        from huggingface_hub import scan_cache_dir
        info = scan_cache_dir()
    except Exception:
        return []
    out = []
    for repo in info.repos:
        if repo.repo_type != "model":
            continue
        out.append({"repo": repo.repo_id, "size": repo.size_on_disk, "last_used": repo.last_accessed})
    out.sort(key=lambda r: r["repo"].lower())
    return out


def delete_repo(repo):
    from huggingface_hub import scan_cache_dir
    info = scan_cache_dir()
    for r in info.repos:
        if r.repo_id == repo and r.repo_type == "model":
            strategy = info.delete_revisions(*[rev.commit_hash for rev in r.revisions])
            strategy.execute()
            return True
    return False
