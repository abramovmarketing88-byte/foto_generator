FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    QT_QPA_PLATFORM=offscreen

WORKDIR /app

# OpenCV/MediaPipe headless: avoid "libxcb.so.1: cannot open shared object file"
RUN apt-get update && apt-get install -y --no-install-recommends \
    libxcb1 libxcb-shm0 libxcb-xfixes0 \
    libgl1 libglib2.0-0 libsm6 \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app
COPY .env.example ./.env.example

RUN mkdir -p /data/storage
ENV STORAGE_DIR=/data/storage

# Single entry point: one process runs bot + worker. Do not add a second service (avoids TelegramConflictError).
CMD ["python", "-m", "app.bot.main"]
