# Foto Generator Telegram SaaS Bot

Production-ready skeleton for Telegram bot (aiogram v3) with enroll + template-based generation flow via NanoBanana API.

## Stack
- Python 3.11
- aiogram v3
- PostgreSQL + async SQLAlchemy 2.0 + Alembic
- Redis + Arq
- Storage abstraction: local / S3
- pydantic-settings
- JSON logging
- pytest

## Flow
1. `/start` creates `User` + personal `Workspace` (FREE, 3 credits).
2. `/enroll` FSM accepts exactly 5 photos and queues ENROLL job.
3. `/templates` shows active templates from DB (seeded from `app/domain/seed_templates.json`).
4. Template selection queues GENERATE job.
5. Worker sends status updates and final media group to user.

## Free / Paid
- Free: 3 credits, 1 enroll.
- Paid: admin can grant credits and change plan.
- Payments layer prepared via `PaymentsService` and `Purchase` model.
- Telegram Stars / Star Subscriptions should be integrated separately into the payments layer.

## Admin commands
- `/admin_grant_credits workspace_id amount`
- `/admin_set_plan workspace_id FREE|PRO`

## Run locally
```bash
cp .env.example .env
docker compose up --build
```

## Migrations
```bash
alembic upgrade head
```

## Tests
```bash
pytest -q
```
