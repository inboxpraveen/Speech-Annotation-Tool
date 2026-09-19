# Providers and models

Every engine receives 16 kHz mono WAV and returns plain text. Engines with a hard length limit get long audio cut at silences first; the pieces are transcribed one after another and joined.

The catalog below is what the app ships with. Every local engine also accepts a custom Hugging Face repo id, and every hosted provider accepts a custom model name, so new releases can be used without a code change. Use **Test with sample clip** on the Models or Providers page to confirm a choice before starting a large job.

Verified on 19 September 2026 against the providers' current documentation. Hosted providers change their model line-up from time to time; when a model is retired, type its replacement in the custom model field.

## Local engines

Models download from Hugging Face into `data/models/huggingface` on first use, or from the Models page. Downloads are jobs, so they show progress and can be cancelled.

### Whisper through faster-whisper

CTranslate2 build of OpenAI Whisper. Quick on a CPU with int8 (the default), and the most widely tested option. 99 languages, automatic language detection.

| Model | Size | Notes |
|---|---|---|
| tiny, tiny.en | 75 MB | fastest, rough |
| base, base.en | 145 MB | good for quick drafts |
| small, small.en | 480 MB | best balance on a CPU |
| medium, medium.en | 1.5 GB | accurate, slow without a GPU |
| large-v3-turbo | 1.6 GB | close to large-v3 quality, much faster |
| large-v3 | 3 GB | best Whisper quality |
| distil-large-v3.5 | 1.5 GB | English only, fast |

Custom: any CTranslate2 Whisper repo, for example `Systran/faster-whisper-large-v3` or a fine-tune converted with `ct2-transformers-converter`.

Options: beam size, VAD filter (skips silence), initial prompt (vocabulary hints), compute type override.

### Parakeet and Canary through onnx-asr

NVIDIA NeMo models exported to ONNX and run with onnxruntime. No NeMo installation, works on Windows, quick on a CPU. Quantized int8 files are used on the CPU by default (about a quarter of the download), full precision on a GPU.

| Model | Languages | Notes |
|---|---|---|
| nemo-parakeet-tdt-0.6b-v3 | 25 European languages, automatic detection | recommended, int8 about 670 MB |
| nemo-parakeet-tdt-0.6b-v2 | English | punctuation and casing |
| nemo-parakeet-ctc-0.6b | English | lightest |
| nemo-canary-1b-v2 | 25 languages, needs a language code | int8 about 1 GB |
| whisper-base | 99 languages | Whisper base as ONNX |
| gigaam-v3-e2e-rnnt | Russian | |

Recordings longer than 25 seconds are processed with the built-in Silero VAD so long files work. Custom: any onnx-asr compatible repo such as `onnx-community/whisper-large-v3-turbo`.

Options: quantization (`auto`, `int8`, `none`).

### Hugging Face Transformers

Any model that works with `pipeline("automatic-speech-recognition")`. Slower than the two engines above on a CPU, but the widest choice. Catalog entries: `openai/whisper-large-v3-turbo`, `openai/whisper-small`, `openai/whisper-base`, `distil-whisper/distil-large-v3.5`, `facebook/wav2vec2-base-960h`, `UsefulSensors/moonshine-base`, `ai4bharat/indicwav2vec-hindi`. Type any other repo id in the custom field. Models that need their own code (for example `CohereLabs/cohere-transcribe-03-2026`) require the "allow custom model code" option and may need a newer transformers release; test first.

### AI4Bharat IndicConformer

`ai4bharat/indic-conformer-600m-multilingual`, 600M parameters, 22 Indian languages: as, bn, brx, doi, gu, hi, kn, kok, ks, mai, ml, mni, mr, ne, or, pa, sa, sat, sd, ta, te, ur. The language must be set on the project. Decoding can be `rnnt` (default) or `ctc`.

The repository is gated. Accept the terms on the model page while signed in to Hugging Face, create a token at huggingface.co/settings/tokens, and save it under Models > Hugging Face token. Audio longer than 30 seconds is split before transcription.

### Qwen3-ASR

`Qwen/Qwen3-ASR-0.6B` and `Qwen/Qwen3-ASR-1.7B`, 52 languages and dialects with automatic detection. Needs the optional package: `pip install qwen-asr` inside the app environment, then restart. Runs on the CPU but is meant for a GPU.

## Hosted providers

Keys are stored in the app database (Providers page, admins only). The base URL is editable for proxies and regional endpoints. Requests that hit a rate limit or a server error are retried three times.

### OpenAI

`POST {base}/audio/transcriptions`. Models: `gpt-4o-mini-transcribe` (default), `gpt-4o-transcribe`, `gpt-transcribe`, `whisper-1`. Files up to 25 MB, so audio longer than 10 minutes is split. Language as ISO 639-1 (`en`, `hi`); `gpt-transcribe` receives it as a language hint list. Option: prompt.

### Groq

OpenAI compatible endpoint at `https://api.groq.com/openai/v1`. Models: `whisper-large-v3-turbo` (default), `whisper-large-v3`. 25 MB per request on the free tier, 100 MB on paid tiers; audio is split at 10 minutes.

### Deepgram

`POST https://api.deepgram.com/v1/listen` with the audio as the request body. Models: `nova-3` (default), `nova-3-medical`, `nova-2`. Language as BCP-47 (`en`, `en-IN`, `hi`) or `multi` for mixed-language audio; blank enables detection. Options: smart formatting, key terms (nova-3).

### ElevenLabs Scribe

`POST https://api.elevenlabs.io/v1/speech-to-text`. Models: `scribe_v2` (default), `scribe_v2_medical`, `scribe_v1`. 90+ languages, ISO 639-1 or 639-3 codes, blank detects. Option: tag audio events such as laughter.

### Sarvam

`POST https://api.sarvam.ai/speech-to-text`. Models: `saaras:v4` (default), `saaras:v3`. Languages: `hi-IN`, `bn-IN`, `ta-IN`, `te-IN`, `kn-IN`, `ml-IN`, `mr-IN`, `gu-IN`, `pa-IN`, `od-IN`, `en-IN` and the other Indian language codes, or `unknown` for detection (used when the project language is blank). The synchronous endpoint takes 30 seconds per request, so audio is split into pieces under 29 seconds. Option: mode (`transcribe`, `verbatim`, `translit`, `codemix`).

### AssemblyAI

Upload to `/v2/upload`, create a transcript, poll until done. Models: `universal-3-5-pro` (default), `universal-2`, `slam-1`. Blank language enables detection. Files up to 2.2 GB.

### Google Gemini

Interactions API at `https://generativelanguage.googleapis.com/v1beta/interactions`. `gemini-3.5-transcribe` (default) is the dedicated transcription model: language hints as BCP-47 codes (`en-US`, `hi-IN`), verbatim or smart mode, up to one hour of audio per request. General models such as `gemini-3.8-flash` or `gemini-2.5-flash` are driven by a transcription prompt that you can change. Audio under 14 MB is sent inline; larger files go through the Files API first.

### Mistral Voxtral

`POST https://api.mistral.ai/v1/audio/transcriptions`, model `voxtral-mini-latest` (Voxtral Mini Transcribe 2). Language as ISO 639-1, blank detects.

### OpenRouter

Chat completions with the audio attached as `input_audio`. Works with any model whose input modalities include audio; the Providers page can fetch the current list from OpenRouter. Default `google/gemini-2.5-flash`. The model is asked to return the plain transcript. Audio longer than 15 minutes is split. Option: prompt.

### Custom OpenAI compatible server

Any server that exposes `/audio/transcriptions` in the OpenAI shape: Speaches, LocalAI, vLLM, whisper.cpp server, LM Studio, Fireworks, DeepInfra and others. Set the base URL (for example `http://localhost:8080/v1`), the model name the server expects, and a key if it needs one.

## Choosing

- Fast and private on a laptop: Whisper `small` (faster-whisper) or Parakeet TDT v3.
- Best quality without a GPU budget: Groq `whisper-large-v3-turbo` or Deepgram `nova-3`.
- Indian languages: IndicConformer locally, Sarvam `saaras:v4` hosted, Whisper `large-v3-turbo` as a general fallback.
- Mixed languages in one recording: Deepgram with `multi`, Gemini 3.5 Transcribe, or Parakeet v3 for European languages.
- Air-gapped machines: any local engine; download the models on a connected machine, copy `data/models`, done.
