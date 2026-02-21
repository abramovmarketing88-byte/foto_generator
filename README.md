# NeuroPhotoshoot MVP (Telegram Bot)

Production-ready MVP репозиторий Telegram-бота на `aiogram v3` с long polling, SQLite (SQLAlchemy 2.x), локальным файловым storage и готовностью к деплою на Railway.

## Стек
- Python 3.11
- aiogram v3
- SQLAlchemy 2.x + SQLite
- pydantic-settings
- Docker (Railway)

## Структура
```text
app/
  __init__.py
  config.py
  logging_setup.py
  db.py
  models.py
  repo.py
  storage.py
  bot/
    main.py
.env.example
.gitignore
Dockerfile
railway.json
requirements.txt
README.md
```

## Переменные окружения
Обязательные:
- `TELEGRAM_BOT_TOKEN`
- `GEMINI_API_KEY`
- `NANOBANANA_API_KEY`

Опциональные (есть значения по умолчанию):
- `DATABASE_URL` (по умолчанию `sqlite+pysqlite:///./storage/neurophotoshoot.db`)
- `STORAGE_DIR` (по умолчанию `./storage`; для Railway рекомендуемо `/data/storage`)
- `MAX_PHOTOS_PER_USER` (по умолчанию `20`)
- `MAX_CONCURRENT_JOBS_PER_USER` (по умолчанию `2`)

## Локальный запуск
1. Создайте виртуальное окружение и установите зависимости:
   ```bash
   python -m venv .venv
   source .venv/bin/activate
   pip install -r requirements.txt
   ```
2. Создайте `.env` из примера:
   ```bash
   cp .env.example .env
   ```
3. Заполните значения переменных в `.env`.
4. Запустите бота:
   ```bash
   python -m app.bot.main
   ```

## Деплой: GitHub → Railway → Variables → Deploy
1. **GitHub**
   - Создайте репозиторий и запушьте этот проект.
2. **Railway**
   - New Project → Deploy from GitHub Repo → выберите репозиторий.
3. **Variables**
   - Добавьте переменные:
     - `TELEGRAM_BOT_TOKEN`
     - `GEMINI_API_KEY`
     - `NANOBANANA_API_KEY`
     - `DATABASE_URL=sqlite+pysqlite:////data/storage/neurophotoshoot.db`
     - `STORAGE_DIR=/data/storage`
     - `MAX_PHOTOS_PER_USER=20`
     - `MAX_CONCURRENT_JOBS_PER_USER=2`
4. **Deploy**
   - Railway соберёт контейнер через `Dockerfile`.
   - Команда запуска: `python -m app.bot.main`.

## Что делает MVP
- Принимает фото от пользователя.
- Сохраняет оригинал в `STORAGE_DIR/raw/<user_id>/`.
- Создаёт задачу генерации в SQLite.
- Фоновый worker в том же процессе обрабатывает очередь задач.
- Для MVP результат имитируется копированием исходного фото в `STORAGE_DIR/results/<user_id>/`.

## Подготовка к S3
`app/storage.py` инкапсулирует работу с файловым хранилищем. Для перехода на S3 можно заменить реализацию методов сохранения/чтения без изменения бизнес-логики хендлеров.
