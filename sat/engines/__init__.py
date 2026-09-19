"""Engine registry: one place that knows every local engine and API provider.

The catalog drives the UI (pickers, option fields, help text) and the
transcribe() entry point picks the right backend for a project.
"""
from pathlib import Path

from sat import audio, db
from sat.engines import api as api_engines
from sat.engines import local as local_engines

WHISPER_LANGS = "auto or an ISO 639-1 code such as en, hi, ta, fr"

CATALOG = [
    {
        "id": "faster_whisper",
        "name": "Whisper (faster-whisper, local)",
        "kind": "local",
        "description": "OpenAI Whisper models running through CTranslate2. Good default on CPU with int8; 99 languages.",
        "default_model": "base",
        "custom_model": True,
        "custom_model_hint": "Any CTranslate2 Whisper repo on Hugging Face, for example Systran/faster-whisper-large-v3",
        "language_hint": WHISPER_LANGS,
        "max_seconds": None,
        "models": [
            {"id": "tiny", "name": "tiny", "note": "75 MB, fastest, rough"},
            {"id": "base", "name": "base", "note": "145 MB, quick drafts"},
            {"id": "small", "name": "small", "note": "480 MB, good balance on CPU"},
            {"id": "medium", "name": "medium", "note": "1.5 GB, accurate, slow on CPU"},
            {"id": "large-v3-turbo", "name": "large-v3-turbo", "note": "1.6 GB, near large-v3 quality, much faster"},
            {"id": "large-v3", "name": "large-v3", "note": "3 GB, best Whisper quality"},
            {"id": "distil-large-v3.5", "name": "distil-large-v3.5", "note": "1.5 GB, English only, fast"},
            {"id": "tiny.en", "name": "tiny.en", "note": "English only"},
            {"id": "base.en", "name": "base.en", "note": "English only"},
            {"id": "small.en", "name": "small.en", "note": "English only"},
            {"id": "medium.en", "name": "medium.en", "note": "English only"},
        ],
        "options": [
            {"key": "beam_size", "label": "Beam size", "type": "number", "default": 5},
            {"key": "vad_filter", "label": "Skip silence with VAD", "type": "bool", "default": True},
            {"key": "initial_prompt", "label": "Initial prompt (vocabulary hints)", "type": "text", "default": ""},
            {"key": "compute_type", "label": "Compute type (blank = auto)", "type": "text", "default": ""},
        ],
    },
    {
        "id": "onnx_asr",
        "name": "Parakeet / Canary (onnx-asr, local)",
        "kind": "local",
        "description": "NVIDIA Parakeet TDT and Canary through onnxruntime. Runs well on CPU; no NeMo install needed.",
        "default_model": "nemo-parakeet-tdt-0.6b-v3",
        "custom_model": True,
        "custom_model_hint": "Any onnx-asr compatible repo, for example onnx-community/whisper-large-v3-turbo",
        "language_hint": "Parakeet v3 detects the language itself (25 European languages). Canary and Whisper take a code such as en, de, fr.",
        "max_seconds": None,
        "models": [
            {"id": "nemo-parakeet-tdt-0.6b-v3", "name": "Parakeet TDT 0.6B v3", "note": "25 European languages, auto language id, int8 ~670 MB"},
            {"id": "nemo-parakeet-tdt-0.6b-v2", "name": "Parakeet TDT 0.6B v2", "note": "English, punctuation and casing"},
            {"id": "nemo-parakeet-ctc-0.6b", "name": "Parakeet CTC 0.6B", "note": "English, lightest"},
            {"id": "nemo-canary-1b-v2", "name": "Canary 1B v2", "note": "25 languages, needs a language code, int8 ~1 GB"},
            {"id": "whisper-base", "name": "Whisper base (ONNX)", "note": "Whisper base exported to ONNX"},
            {"id": "gigaam-v3-e2e-rnnt", "name": "GigaAM v3 RNNT", "note": "Russian"},
        ],
        "options": [
            {"key": "quantization", "label": "Quantization (auto, int8 or none)", "type": "text", "default": "auto"},
        ],
    },
    {
        "id": "transformers",
        "name": "Hugging Face Transformers (local)",
        "kind": "local",
        "description": "Any model the transformers speech recognition pipeline supports: Whisper, Distil-Whisper, wav2vec2, Moonshine and more.",
        "default_model": "openai/whisper-small",
        "custom_model": True,
        "custom_model_hint": "Any Hugging Face repo id that works with pipeline('automatic-speech-recognition')",
        "language_hint": WHISPER_LANGS,
        "max_seconds": None,
        "models": [
            {"id": "openai/whisper-large-v3-turbo", "name": "openai/whisper-large-v3-turbo", "note": "1.6 GB, 99 languages"},
            {"id": "openai/whisper-small", "name": "openai/whisper-small", "note": "970 MB"},
            {"id": "openai/whisper-base", "name": "openai/whisper-base", "note": "290 MB"},
            {"id": "distil-whisper/distil-large-v3.5", "name": "distil-whisper/distil-large-v3.5", "note": "English, fast"},
            {"id": "facebook/wav2vec2-base-960h", "name": "facebook/wav2vec2-base-960h", "note": "English, tiny and quick"},
            {"id": "UsefulSensors/moonshine-base", "name": "UsefulSensors/moonshine-base", "note": "English, built for low power CPUs"},
            {"id": "ai4bharat/indicwav2vec-hindi", "name": "ai4bharat/indicwav2vec-hindi", "note": "Hindi wav2vec2"},
        ],
        "options": [
            {"key": "trust_remote_code", "label": "Allow custom model code (trust_remote_code)", "type": "bool", "default": False},
        ],
    },
    {
        "id": "indic_conformer",
        "name": "AI4Bharat IndicConformer (local)",
        "kind": "local",
        "description": "IndicConformer 600M for 22 Indian languages. The Hugging Face repo is gated: accept its terms and add your HF token under Settings.",
        "default_model": "ai4bharat/indic-conformer-600m-multilingual",
        "custom_model": True,
        "custom_model_hint": "A repo with the same custom model code",
        "language_hint": "Required. One of: as, bn, brx, doi, gu, hi, kn, kok, ks, mai, ml, mni, mr, ne, or, pa, sa, sat, sd, ta, te, ur",
        "max_seconds": 30,
        "models": [
            {"id": "ai4bharat/indic-conformer-600m-multilingual", "name": "IndicConformer 600M multilingual", "note": "22 Indian languages, CTC or RNNT decoding"},
        ],
        "options": [
            {"key": "decoding", "label": "Decoding (ctc or rnnt)", "type": "text", "default": "rnnt"},
        ],
    },
    {
        "id": "qwen_asr",
        "name": "Qwen3-ASR (local, optional)",
        "kind": "local",
        "description": "Qwen3-ASR through the qwen-asr package (pip install qwen-asr). 52 languages and dialects.",
        "default_model": "Qwen/Qwen3-ASR-0.6B",
        "custom_model": True,
        "custom_model_hint": "Qwen/Qwen3-ASR-0.6B or Qwen/Qwen3-ASR-1.7B",
        "language_hint": "Leave blank for automatic detection, or give a language name such as English, Chinese, Hindi",
        "max_seconds": None,
        "models": [
            {"id": "Qwen/Qwen3-ASR-0.6B", "name": "Qwen3-ASR 0.6B", "note": "small and quick"},
            {"id": "Qwen/Qwen3-ASR-1.7B", "name": "Qwen3-ASR 1.7B", "note": "more accurate"},
        ],
        "options": [],
    },
    # Hosted providers ------------------------------------------------------------
    {
        "id": "openai",
        "name": "OpenAI",
        "kind": "api",
        "description": "OpenAI transcription API. Files up to 25 MB; long audio is split automatically.",
        "default_model": "gpt-4o-mini-transcribe",
        "custom_model": True,
        "language_hint": "ISO 639-1 code such as en, hi. Blank = auto",
        "max_seconds": 600,
        "key_label": "OpenAI API key",
        "base_url": "https://api.openai.com/v1",
        "docs": "https://developers.openai.com/api/docs/guides/speech-to-text",
        "models": [
            {"id": "gpt-4o-mini-transcribe", "name": "gpt-4o-mini-transcribe", "note": "cheap and accurate"},
            {"id": "gpt-4o-transcribe", "name": "gpt-4o-transcribe", "note": "most accurate 4o model"},
            {"id": "gpt-transcribe", "name": "gpt-transcribe", "note": "newest, multilingual hints"},
            {"id": "whisper-1", "name": "whisper-1", "note": "classic Whisper large-v2"},
        ],
        "options": [
            {"key": "prompt", "label": "Prompt (vocabulary or style hints)", "type": "text", "default": ""},
        ],
    },
    {
        "id": "groq",
        "name": "Groq",
        "kind": "api",
        "description": "Whisper large-v3 on Groq hardware, very fast. 25 MB per request on the free tier.",
        "default_model": "whisper-large-v3-turbo",
        "custom_model": True,
        "language_hint": "ISO 639-1 code such as en, hi. Blank = auto",
        "max_seconds": 600,
        "key_label": "Groq API key",
        "base_url": "https://api.groq.com/openai/v1",
        "docs": "https://console.groq.com/docs/speech-to-text",
        "models": [
            {"id": "whisper-large-v3-turbo", "name": "whisper-large-v3-turbo", "note": "fast"},
            {"id": "whisper-large-v3", "name": "whisper-large-v3", "note": "most accurate"},
        ],
        "options": [
            {"key": "prompt", "label": "Prompt (vocabulary or style hints)", "type": "text", "default": ""},
        ],
    },
    {
        "id": "deepgram",
        "name": "Deepgram",
        "kind": "api",
        "description": "Deepgram Nova models. Use language 'multi' for mixed language audio.",
        "default_model": "nova-3",
        "custom_model": True,
        "language_hint": "BCP-47 such as en, en-IN, hi, or multi. Blank = detect",
        "max_seconds": None,
        "key_label": "Deepgram API key",
        "base_url": "https://api.deepgram.com/v1",
        "docs": "https://developers.deepgram.com/reference/speech-to-text/listen-pre-recorded",
        "models": [
            {"id": "nova-3", "name": "nova-3", "note": "latest general model"},
            {"id": "nova-3-medical", "name": "nova-3-medical", "note": "medical vocabulary"},
            {"id": "nova-2", "name": "nova-2", "note": "previous generation"},
        ],
        "options": [
            {"key": "smart_format", "label": "Smart formatting", "type": "bool", "default": True},
            {"key": "keyterms", "label": "Key terms (comma separated, nova-3 only)", "type": "text", "default": ""},
        ],
    },
    {
        "id": "elevenlabs",
        "name": "ElevenLabs Scribe",
        "kind": "api",
        "description": "ElevenLabs Scribe speech to text, 90+ languages.",
        "default_model": "scribe_v2",
        "custom_model": True,
        "language_hint": "ISO 639-1 or 639-3 code. Blank = detect",
        "max_seconds": None,
        "key_label": "ElevenLabs API key",
        "base_url": "https://api.elevenlabs.io/v1",
        "docs": "https://elevenlabs.io/docs/api-reference/speech-to-text/convert",
        "models": [
            {"id": "scribe_v2", "name": "scribe_v2", "note": "current model"},
            {"id": "scribe_v2_medical", "name": "scribe_v2_medical", "note": "clinical audio"},
            {"id": "scribe_v1", "name": "scribe_v1", "note": "previous model"},
        ],
        "options": [
            {"key": "tag_audio_events", "label": "Tag audio events such as (laughter)", "type": "bool", "default": False},
        ],
    },
    {
        "id": "sarvam",
        "name": "Sarvam AI",
        "kind": "api",
        "description": "Sarvam Saaras for Indian languages. The REST endpoint takes up to 30 seconds per request, so audio is split automatically.",
        "default_model": "saaras:v4",
        "custom_model": True,
        "language_hint": "hi-IN, en-IN, ta-IN and other -IN codes, or unknown for detection",
        "max_seconds": 29,
        "key_label": "Sarvam API subscription key",
        "base_url": "https://api.sarvam.ai",
        "docs": "https://docs.sarvam.ai/api-reference-docs/speech-to-text/transcribe",
        "models": [
            {"id": "saaras:v4", "name": "saaras:v4", "note": "latest, Indic plus global English"},
            {"id": "saaras:v3", "name": "saaras:v3", "note": "previous"},
        ],
        "options": [
            {"key": "mode", "label": "Mode (transcribe, verbatim, translit, codemix)", "type": "text", "default": "transcribe"},
        ],
    },
    {
        "id": "assemblyai",
        "name": "AssemblyAI",
        "kind": "api",
        "description": "AssemblyAI async transcription (upload, then poll).",
        "default_model": "universal-3-5-pro",
        "custom_model": True,
        "language_hint": "ISO 639-1 code. Blank = detect",
        "max_seconds": None,
        "key_label": "AssemblyAI API key",
        "base_url": "https://api.assemblyai.com",
        "docs": "https://www.assemblyai.com/docs/speech-to-text/pre-recorded-audio",
        "models": [
            {"id": "universal-3-5-pro", "name": "universal-3-5-pro", "note": "recommended"},
            {"id": "universal-2", "name": "universal-2", "note": "99 languages"},
            {"id": "slam-1", "name": "slam-1", "note": "promptable"},
        ],
        "options": [],
    },
    {
        "id": "gemini",
        "name": "Google Gemini",
        "kind": "api",
        "description": "Gemini 3.5 Transcribe or any audio-capable Gemini model through the Interactions API.",
        "default_model": "gemini-3.5-transcribe",
        "custom_model": True,
        "language_hint": "BCP-47 such as en-US, hi-IN. Blank = detect",
        "max_seconds": 3000,
        "key_label": "Gemini API key",
        "base_url": "https://generativelanguage.googleapis.com",
        "docs": "https://ai.google.dev/gemini-api/docs/transcribe",
        "models": [
            {"id": "gemini-3.5-transcribe", "name": "gemini-3.5-transcribe", "note": "dedicated transcription model"},
            {"id": "gemini-3.8-flash", "name": "gemini-3.8-flash", "note": "general model, prompt based"},
            {"id": "gemini-2.5-flash", "name": "gemini-2.5-flash", "note": "general model, prompt based"},
        ],
        "options": [
            {"key": "mode", "label": "Mode for gemini-3.5-transcribe (verbatim or smart)", "type": "text", "default": "verbatim"},
            {"key": "prompt", "label": "Prompt for general models", "type": "text", "default": ""},
        ],
    },
    {
        "id": "mistral",
        "name": "Mistral Voxtral",
        "kind": "api",
        "description": "Mistral Voxtral transcription API.",
        "default_model": "voxtral-mini-latest",
        "custom_model": True,
        "language_hint": "ISO 639-1 code. Blank = detect",
        "max_seconds": None,
        "key_label": "Mistral API key",
        "base_url": "https://api.mistral.ai/v1",
        "docs": "https://docs.mistral.ai/studio/audio/speech_to_text/offline_transcription",
        "models": [
            {"id": "voxtral-mini-latest", "name": "voxtral-mini-latest", "note": "Voxtral Mini Transcribe 2"},
        ],
        "options": [],
    },
    {
        "id": "openrouter",
        "name": "OpenRouter",
        "kind": "api",
        "description": "Any audio-capable chat model on OpenRouter (Gemini, GPT audio, Voxtral and others). Prompt based.",
        "default_model": "google/gemini-2.5-flash",
        "custom_model": True,
        "language_hint": "Language name or code added to the prompt. Blank = let the model decide",
        "max_seconds": 900,
        "key_label": "OpenRouter API key",
        "base_url": "https://openrouter.ai/api/v1",
        "docs": "https://openrouter.ai/docs/features/multimodal/audio",
        "models": [
            {"id": "google/gemini-2.5-flash", "name": "google/gemini-2.5-flash", "note": "good and cheap"},
            {"id": "google/gemini-3.5-flash-lite", "name": "google/gemini-3.5-flash-lite", "note": "cheapest recent Gemini"},
            {"id": "openai/gpt-audio-mini", "name": "openai/gpt-audio-mini", "note": "OpenAI audio model"},
            {"id": "mistralai/voxtral-small-24b-2507", "name": "mistralai/voxtral-small-24b-2507", "note": "Voxtral Small"},
        ],
        "options": [
            {"key": "prompt", "label": "Prompt", "type": "text", "default": ""},
        ],
    },
    {
        "id": "custom_openai",
        "name": "Custom OpenAI-compatible server",
        "kind": "api",
        "description": "Any server exposing /audio/transcriptions: Speaches, LocalAI, vLLM, whisper.cpp server, LM Studio, Fireworks, DeepInfra.",
        "default_model": "whisper-1",
        "custom_model": True,
        "language_hint": "ISO 639-1 code. Blank = auto",
        "max_seconds": None,
        "key_label": "API key (optional)",
        "base_url": "",
        "docs": "",
        "models": [],
        "options": [],
    },
]

BY_ID = {e["id"]: e for e in CATALOG}


def get(engine_id):
    e = BY_ID.get(engine_id)
    if e is None:
        raise ValueError("unknown engine %s" % engine_id)
    return e


def catalog_with_status():
    """Catalog plus install / key state for the UI."""
    caps = local_engines.capabilities()
    out = []
    for e in CATALOG:
        item = dict(e)
        if e["kind"] == "local":
            item["installed"] = bool(caps.get(e["id"]))
            item["pip_hint"] = {
                "faster_whisper": "pip install faster-whisper",
                "onnx_asr": "pip install onnx-asr[cpu,hub]",
                "transformers": "pip install torch transformers",
                "indic_conformer": "pip install torch transformers",
                "qwen_asr": "pip install qwen-asr",
            }.get(e["id"], "")
        else:
            item["has_key"] = bool(api_engines.setting(e["id"], "api_key"))
            item["base_url_current"] = api_engines.setting(e["id"], "base_url", e.get("base_url", ""))
            item["default_model_current"] = api_engines.setting(e["id"], "model", e["default_model"])
        out.append(item)
    return out


def engine_options(engine_id, project_options):
    """Merge provider level defaults (Providers page) with project overrides."""
    merged = {}
    for opt in get(engine_id).get("options", []):
        merged[opt["key"]] = opt.get("default")
    stored = db.get_setting("engine.%s.options" % engine_id) or {}
    if isinstance(stored, dict):
        merged.update({k: v for k, v in stored.items() if v not in (None, "")})
    if isinstance(project_options, dict):
        merged.update({k: v for k, v in project_options.items() if v not in (None, "")})
    return merged


def transcribe(engine_id, model, wav_path, language=None, options=None):
    """Transcribe a 16 kHz WAV with any engine, splitting when the engine has a length limit."""
    e = get(engine_id)
    options = options or {}
    max_seconds = e.get("max_seconds")
    pieces = [Path(wav_path)]
    if max_seconds:
        pieces = audio.split_wav_for_engine(wav_path, max_seconds)
    texts, lang = [], None
    try:
        for piece in pieces:
            if e["kind"] == "local":
                res = local_engines.transcribe(engine_id, model, piece, language, options)
            else:
                res = api_engines.transcribe(engine_id, model, piece, language, options)
            if res.get("text"):
                texts.append(res["text"])
            lang = lang or res.get("language")
    finally:
        for piece in pieces:
            if piece != Path(wav_path):
                try:
                    piece.unlink()
                except OSError:
                    pass
    return {"text": " ".join(texts).strip(), "language": lang}
