# NeuroPhotoshoot MVP (Telegram Bot)

Production-ready Telegram bot on `aiogram v3` with SQLite/SQLAlchemy, local storage, async AI processing pipeline, and in-process background worker suitable for Railway.

## Stack
- Python 3.11
- aiogram v3
- SQLAlchemy 2.x + SQLite
- pydantic-settings
- httpx (async HTTP clients)
- Pillow (image resize/optimization)
- Docker (Railway)

## Updated project tree
```text
app/
  __init__.py
  config.py
  logging_setup.py
  db.py
  models.py
  repo.py
  prompt_builder.py
  queue.py
  storage.py
  worker.py
  ai/
    __init__.py
    gemini_analyzer.py
    nanobanana_client.py
  bot/
    main.py
.env.example
.gitignore
Dockerfile
railway.json
requirements.txt
README.md
```

## AI architecture (strict role separation)
- **Gemini Flash** is used **only** for multimodal face photo analysis.
  - Input: FACE photo bytes.
  - Output: `face_signature_text` + `warnings[]`.
  - If Gemini fails after retries, worker continues with empty signature.
- **NanoBanana** is used **only** for final image generation.
  - Input: deterministic `final_prompt` + reference photos.
  - Output: generated image bytes.

### Processing flow per job
1. User presses `Генерация` → job is created with `QUEUED` status.
2. Worker polls queue and sets job to `RUNNING`.
3. Worker loads reference photos from storage.
4. Worker analyzes FACE photos using Gemini analyzer.
5. Worker builds deterministic prompt in required 7-block format.
6. Worker calls NanoBanana generation API.
7. Worker stores result image, inserts `Generation`, marks job `SUCCEEDED`.
8. Worker sends generated image to Telegram with lens/angle/size caption.
9. Any exception → mark `FAILED`, save error text, notify user.

## Environment variables
Required:
- `TELEGRAM_BOT_TOKEN`
- `GEMINI_API_KEY`
- `NANOBANANA_API_KEY`

Optional (safe defaults):
- `GEMINI_ANALYSIS_MODEL=gemini-2.0-flash`
- `GEMINI_RETRIES=3`
- `NANOBANANA_BASE_URL=https://api.nanobanana.example`
- `NANOBANANA_GENERATE_PATH=/v1/generate`
- `NANOBANANA_TIMEOUT_SEC=60`
- `NANOBANANA_RETRIES=5`
- `JOB_TIMEOUT_SEC=120`
- `DATABASE_URL=sqlite+pysqlite:///./storage/neurophotoshoot.db`
- `STORAGE_DIR=./storage` (Railway recommended: `/data/storage`)
- `MAX_PHOTOS_PER_USER=20`
- `MAX_CONCURRENT_JOBS_PER_USER=2`

## Worker lifecycle
- Worker runs in the same process as bot polling (`asyncio.create_task`).
- On startup, all stale `RUNNING` jobs are marked `FAILED` with `service restart`.
- Main loop is resilient and wrapped with `try/except`, so polling is not killed by worker errors.
- Each job execution is guarded by `JOB_TIMEOUT_SEC`.
- Graceful shutdown: stop event is set and worker task is cancelled safely.

## Local run
1. Create venv and install dependencies:
   ```bash
   python -m venv .venv
   source .venv/bin/activate
   pip install -r requirements.txt
   ```
2. Create env file:
   ```bash
   cp .env.example .env
   ```
3. Fill required vars in `.env`.
4. Start bot:
   ```bash
   python -m app.bot.main
   ```

## Railway deployment notes
1. Deploy from GitHub repository in Railway.
2. Add environment variables:
   - `TELEGRAM_BOT_TOKEN`
   - `GEMINI_API_KEY`
   - `NANOBANANA_API_KEY`
   - `DATABASE_URL=sqlite+pysqlite:////data/storage/neurophotoshoot.db`
   - `STORAGE_DIR=/data/storage`
   - Optional tuning values for retries/timeouts/models.
3. Keep persistent volume mounted for `/data/storage`.
4. Start command remains:
   ```bash
   python -m app.bot.main
   ```

## Safety/logging notes
- Never log API keys or raw image bytes.
- Prompt text is logged for traceability.
- Worker and handlers are guarded with error handling to preserve service stability.
