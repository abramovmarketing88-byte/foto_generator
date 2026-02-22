FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app
COPY .env.example ./.env.example

RUN mkdir -p /data/storage
ENV STORAGE_DIR=/data/storage

# Single entry point: one process runs bot + worker. Do not add a second service (avoids TelegramConflictError).
CMD ["python", "-m", "app.bot.main"]
