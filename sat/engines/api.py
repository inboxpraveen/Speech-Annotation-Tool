"""Hosted speech-to-text providers.

Every provider gets a 16 kHz mono WAV and returns plain text. Keys, base
URLs and default models live in the settings table (edited in the app).
Long audio is cut at silences before calling providers that have a hard
duration limit (see max_seconds in the catalog).
"""
import base64
import json
import time
from pathlib import Path

import requests

from sat import db

TIMEOUT = 600


class ProviderError(Exception):
    pass


def setting(provider, key, default=""):
    value = db.get_setting("provider.%s.%s" % (provider, key))
    if value in (None, ""):
        return default
    return value


def api_key(provider):
    key = setting(provider, "api_key")
    if not key:
        raise ProviderError("%s: API key is not set. Add it under Providers." % provider)
    return key


def _check(resp, provider):
    if resp.status_code >= 400:
        body = resp.text[:400].replace("\n", " ")
        raise ProviderError("%s returned HTTP %s: %s" % (provider, resp.status_code, body))
    try:
        return resp.json()
    except ValueError:
        raise ProviderError("%s returned a non-JSON response" % provider)


def _post_with_retry(fn, attempts=3):
    last = None
    for i in range(attempts):
        try:
            return fn()
        except (requests.ConnectionError, requests.Timeout) as exc:
            last = exc
            time.sleep(2 * (i + 1))
        except ProviderError as exc:
            last = exc
            text = str(exc)
            if "HTTP 429" in text or "HTTP 5" in text:
                time.sleep(3 * (i + 1))
                continue
            raise
    raise ProviderError("request failed after %d attempts: %s" % (attempts, last))


def _lang2(language):
    """ISO 639-1 style code (en, hi) from whatever the project has."""
    if not language:
        return None
    return language.split("-")[0].split("_")[0].lower()


# OpenAI style ------------------------------------------------------------------

def _openai_compatible(provider, base_url, model, wav_path, language, options, key_header=None):
    url = base_url.rstrip("/") + "/audio/transcriptions"
    headers = key_header or {"Authorization": "Bearer %s" % api_key(provider)}
    data = {"model": model, "response_format": "json"}
    if language:
        if model.startswith("gpt-transcribe"):
            data["languages[]"] = _lang2(language)
        else:
            data["language"] = _lang2(language)
    if options.get("prompt"):
        data["prompt"] = options["prompt"]
    if options.get("temperature") not in (None, ""):
        data["temperature"] = str(options["temperature"])

    def call():
        with open(wav_path, "rb") as fh:
            resp = requests.post(url, headers=headers, data=data, files={"file": (Path(wav_path).name, fh, "audio/wav")}, timeout=TIMEOUT)
        return _check(resp, provider)

    body = _post_with_retry(call)
    text = body.get("text", "")
    lang = body.get("language") or (body.get("languages") or [None])[0]
    return {"text": text.strip(), "language": lang}


def openai(model, wav_path, language, options):
    return _openai_compatible("openai", setting("openai", "base_url", "https://api.openai.com/v1"), model, wav_path, language, options)


def groq(model, wav_path, language, options):
    return _openai_compatible("groq", setting("groq", "base_url", "https://api.groq.com/openai/v1"), model, wav_path, language, options)


def custom_openai(model, wav_path, language, options):
    base = setting("custom_openai", "base_url")
    if not base:
        raise ProviderError("custom_openai: base URL is not set")
    key = setting("custom_openai", "api_key")
    headers = {"Authorization": "Bearer %s" % key} if key else {}
    return _openai_compatible("custom_openai", base, model, wav_path, language, options, key_header=headers)


def mistral(model, wav_path, language, options):
    url = setting("mistral", "base_url", "https://api.mistral.ai/v1").rstrip("/") + "/audio/transcriptions"
    headers = {"Authorization": "Bearer %s" % api_key("mistral")}
    data = {"model": model}
    if language:
        data["language"] = _lang2(language)

    def call():
        with open(wav_path, "rb") as fh:
            resp = requests.post(url, headers=headers, data=data, files={"file": (Path(wav_path).name, fh, "audio/wav")}, timeout=TIMEOUT)
        return _check(resp, "mistral")

    body = _post_with_retry(call)
    return {"text": (body.get("text") or "").strip(), "language": body.get("language")}


# Deepgram ------------------------------------------------------------------------

def deepgram(model, wav_path, language, options):
    params = {"model": model, "smart_format": "true" if options.get("smart_format", True) not in (False, "false", 0) else "false"}
    if options.get("punctuate") not in (None, "", False, "false"):
        params["punctuate"] = "true"
    if language:
        params["language"] = language
    else:
        params["detect_language"] = "true"
    if options.get("keyterms"):
        params["keyterm"] = [k.strip() for k in str(options["keyterms"]).split(",") if k.strip()]
    url = setting("deepgram", "base_url", "https://api.deepgram.com/v1").rstrip("/") + "/listen"
    headers = {"Authorization": "Token %s" % api_key("deepgram"), "Content-Type": "audio/wav"}

    def call():
        with open(wav_path, "rb") as fh:
            resp = requests.post(url, headers=headers, params=params, data=fh, timeout=TIMEOUT)
        return _check(resp, "deepgram")

    body = _post_with_retry(call)
    try:
        alt = body["results"]["channels"][0]["alternatives"][0]
    except (KeyError, IndexError, TypeError):
        raise ProviderError("deepgram: unexpected response shape")
    lang = None
    try:
        lang = body["results"]["channels"][0].get("detected_language")
    except (KeyError, IndexError, TypeError, AttributeError):
        pass
    return {"text": (alt.get("transcript") or "").strip(), "language": lang}


# ElevenLabs ---------------------------------------------------------------------

def elevenlabs(model, wav_path, language, options):
    url = setting("elevenlabs", "base_url", "https://api.elevenlabs.io/v1").rstrip("/") + "/speech-to-text"
    headers = {"xi-api-key": api_key("elevenlabs")}
    data = {"model_id": model, "tag_audio_events": "true" if options.get("tag_audio_events") in (True, "true", 1) else "false"}
    if language:
        data["language_code"] = _lang2(language)
    if options.get("diarize") in (True, "true", 1):
        data["diarize"] = "true"

    def call():
        with open(wav_path, "rb") as fh:
            resp = requests.post(url, headers=headers, data=data, files={"file": (Path(wav_path).name, fh, "audio/wav")}, timeout=TIMEOUT)
        return _check(resp, "elevenlabs")

    body = _post_with_retry(call)
    return {"text": (body.get("text") or "").strip(), "language": body.get("language_code")}


# Sarvam --------------------------------------------------------------------------

def sarvam(model, wav_path, language, options):
    url = setting("sarvam", "base_url", "https://api.sarvam.ai").rstrip("/") + "/speech-to-text"
    headers = {"api-subscription-key": api_key("sarvam")}
    data = {"model": model, "mode": options.get("mode") or "transcribe"}
    code = language or "unknown"
    if "-" not in code and code != "unknown":
        code = code.lower() + "-IN"
    data["language_code"] = code

    def call():
        with open(wav_path, "rb") as fh:
            resp = requests.post(url, headers=headers, data=data, files={"file": (Path(wav_path).name, fh, "audio/wav")}, timeout=TIMEOUT)
        return _check(resp, "sarvam")

    body = _post_with_retry(call)
    return {"text": (body.get("transcript") or "").strip(), "language": body.get("language_code")}


# AssemblyAI ----------------------------------------------------------------------

def assemblyai(model, wav_path, language, options):
    base = setting("assemblyai", "base_url", "https://api.assemblyai.com").rstrip("/")
    headers = {"authorization": api_key("assemblyai")}

    def upload():
        with open(wav_path, "rb") as fh:
            resp = requests.post(base + "/v2/upload", headers=headers, data=fh, timeout=TIMEOUT)
        return _check(resp, "assemblyai")

    upload_url = _post_with_retry(upload).get("upload_url")
    if not upload_url:
        raise ProviderError("assemblyai: upload did not return upload_url")
    payload = {"audio_url": upload_url, "speech_models": [model]}
    if language:
        payload["language_code"] = _lang2(language)
    else:
        payload["language_detection"] = True

    def create():
        resp = requests.post(base + "/v2/transcript", headers=headers, json=payload, timeout=TIMEOUT)
        return _check(resp, "assemblyai")

    created = _post_with_retry(create)
    tid = created.get("id")
    deadline = time.time() + TIMEOUT
    while time.time() < deadline:
        resp = requests.get(base + "/v2/transcript/" + tid, headers=headers, timeout=60)
        body = _check(resp, "assemblyai")
        status = body.get("status")
        if status == "completed":
            return {"text": (body.get("text") or "").strip(), "language": body.get("language_code")}
        if status == "error":
            raise ProviderError("assemblyai: %s" % body.get("error"))
        time.sleep(2)
    raise ProviderError("assemblyai: timed out waiting for transcript")


# Gemini --------------------------------------------------------------------------

def _gemini_upload(base, key, wav_path):
    size = Path(wav_path).stat().st_size
    start = requests.post(
        base + "/upload/v1beta/files",
        headers={
            "x-goog-api-key": key,
            "X-Goog-Upload-Protocol": "resumable",
            "X-Goog-Upload-Command": "start",
            "X-Goog-Upload-Header-Content-Length": str(size),
            "X-Goog-Upload-Header-Content-Type": "audio/wav",
            "Content-Type": "application/json",
        },
        json={"file": {"display_name": Path(wav_path).name}},
        timeout=120,
    )
    if start.status_code >= 400:
        raise ProviderError("gemini upload start failed: HTTP %s %s" % (start.status_code, start.text[:200]))
    upload_url = start.headers.get("X-Goog-Upload-URL") or start.headers.get("x-goog-upload-url")
    if not upload_url:
        raise ProviderError("gemini upload did not return an upload URL")
    with open(wav_path, "rb") as fh:
        done = requests.post(
            upload_url,
            headers={"Content-Length": str(size), "X-Goog-Upload-Offset": "0", "X-Goog-Upload-Command": "upload, finalize"},
            data=fh,
            timeout=TIMEOUT,
        )
    body = _check(done, "gemini")
    info = body.get("file") or {}
    name, uri = info.get("name"), info.get("uri")
    # Wait until the file is processed.
    for _ in range(60):
        if (info.get("state") or "ACTIVE") == "ACTIVE":
            break
        time.sleep(2)
        info = _check(requests.get(base + "/v1beta/" + name, headers={"x-goog-api-key": key}, timeout=60), "gemini")
    return uri


def gemini(model, wav_path, language, options):
    base = setting("gemini", "base_url", "https://generativelanguage.googleapis.com").rstrip("/")
    key = api_key("gemini")
    size = Path(wav_path).stat().st_size
    if size < 14 * 1024 * 1024:
        with open(wav_path, "rb") as fh:
            audio_part = {"type": "audio", "data": base64.b64encode(fh.read()).decode("ascii"), "mime_type": "audio/wav"}
    else:
        audio_part = {"type": "audio", "uri": _gemini_upload(base, key, wav_path), "mime_type": "audio/wav"}
    body = {"model": model, "input": []}
    if "transcribe" in model:
        body["input"] = [audio_part]
        config = {"language_codes": [language] if language else []}
        if options.get("mode") == "smart":
            config["mode"] = "smart"
        body["generation_config"] = {"transcription_config": config}
    else:
        prompt = options.get("prompt") or (
            "Transcribe this audio exactly as spoken. Return only the transcript text, without any commentary, "
            "speaker labels or timestamps."
        )
        if language:
            prompt += " The language is %s." % language
        body["input"] = [{"type": "text", "text": prompt}, audio_part]
    headers = {"x-goog-api-key": key, "Content-Type": "application/json"}
    if "transcribe" not in model:
        # The general audio guide pins the API revision; the transcribe guide does not.
        headers["Api-Revision"] = "2026-05-20"

    def call():
        resp = requests.post(base + "/v1beta/interactions", headers=headers, json=body, timeout=TIMEOUT)
        return _check(resp, "gemini")

    out = _post_with_retry(call)
    texts = []
    for step in out.get("steps") or out.get("outputs") or []:
        if isinstance(step, dict) and step.get("type") not in (None, "model_output", "message", "text"):
            continue
        for content in (step.get("content") or []) if isinstance(step, dict) else []:
            if isinstance(content, dict) and content.get("type") == "text" and content.get("text"):
                texts.append(content["text"])
    if not texts and isinstance(out.get("output_text"), str):
        texts.append(out["output_text"])
    if not texts and out.get("status") == "failed":
        raise ProviderError("gemini: %s" % json.dumps(out.get("error") or out)[:300])
    return {"text": "\n".join(texts).strip(), "language": language}


# OpenRouter (chat completions with audio input) --------------------------------------

def openrouter(model, wav_path, language, options):
    url = setting("openrouter", "base_url", "https://openrouter.ai/api/v1").rstrip("/") + "/chat/completions"
    headers = {
        "Authorization": "Bearer %s" % api_key("openrouter"),
        "Content-Type": "application/json",
        "HTTP-Referer": "https://github.com/inboxpraveen/Speech-Annotation-Tool",
        "X-Title": "Speech Annotation Tool",
    }
    with open(wav_path, "rb") as fh:
        data = base64.b64encode(fh.read()).decode("ascii")
    prompt = options.get("prompt") or (
        "Transcribe this audio exactly as spoken. Return only the transcript text, without any commentary, "
        "speaker labels or timestamps."
    )
    if language:
        prompt += " The language is %s." % language
    body = {
        "model": model,
        "messages": [{"role": "user", "content": [{"type": "text", "text": prompt}, {"type": "input_audio", "input_audio": {"data": data, "format": "wav"}}]}],
        "temperature": 0,
    }

    def call():
        resp = requests.post(url, headers=headers, json=body, timeout=TIMEOUT)
        return _check(resp, "openrouter")

    out = _post_with_retry(call)
    try:
        content = out["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError):
        raise ProviderError("openrouter: unexpected response: %s" % json.dumps(out)[:300])
    if isinstance(content, list):
        content = " ".join(c.get("text", "") for c in content if isinstance(c, dict))
    return {"text": (content or "").strip(), "language": language}


def openrouter_audio_models():
    """Audio-capable models from the OpenRouter catalog (for the picker)."""
    resp = requests.get(setting("openrouter", "base_url", "https://openrouter.ai/api/v1").rstrip("/") + "/models", timeout=60)
    data = _check(resp, "openrouter").get("data", [])
    out = []
    for m in data:
        mods = (m.get("architecture") or {}).get("input_modalities") or []
        if "audio" in mods:
            out.append({"id": m["id"], "name": m.get("name") or m["id"]})
    out.sort(key=lambda m: m["id"])
    return out


RUNNERS = {
    "openai": openai,
    "groq": groq,
    "custom_openai": custom_openai,
    "mistral": mistral,
    "deepgram": deepgram,
    "elevenlabs": elevenlabs,
    "sarvam": sarvam,
    "assemblyai": assemblyai,
    "gemini": gemini,
    "openrouter": openrouter,
}


def transcribe(provider, model, wav_path, language=None, options=None):
    fn = RUNNERS.get(provider)
    if fn is None:
        raise ProviderError("unknown provider %s" % provider)
    return fn(model, str(wav_path), language or None, options or {})
