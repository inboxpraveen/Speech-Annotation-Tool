# Speech Annotation Tool
# CPU image by default. For NVIDIA GPUs build with:
#   docker build --build-arg TORCH_INDEX=https://download.pytorch.org/whl/cu128 -t speech-annotation-tool .
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

ARG TORCH_INDEX=https://download.pytorch.org/whl/cpu
COPY requirements.txt .
RUN pip install --extra-index-url ${TORCH_INDEX} -r requirements.txt

COPY . .

ENV DATA_DIR=/app/data \
    HOST=0.0.0.0 \
    PORT=8000 \
    AUDIO_ROOTS=/audio

VOLUME ["/app/data"]
EXPOSE 8000

CMD ["python", "app.py"]
