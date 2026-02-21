from __future__ import annotations

import asyncio
import logging
from contextlib import suppress
from pathlib import Path

from aiogram import Bot, Dispatcher, F, Router
from aiogram.filters import Command
from aiogram.types import Message
from sqlalchemy.orm import sessionmaker

from app.config import Settings, get_settings
from app.db import create_session_factory
from app.logging_setup import setup_logging
from app.models import Base, JobStatus
from app.repo import NeuroPhotoshootRepo
from app.storage import LocalStorage

logger = logging.getLogger(__name__)
router = Router()


class AppContext:
    def __init__(self, settings: Settings, session_factory: sessionmaker, storage: LocalStorage):
        self.settings = settings
        self.session_factory = session_factory
        self.storage = storage
        self.queue: asyncio.Queue[tuple[int, int, Path]] = asyncio.Queue()
        self.worker_task: asyncio.Task | None = None


@router.message(Command("start"))
async def on_start(message: Message) -> None:
    await message.answer(
        "Привет! Я NeuroPhotoshoot MVP.\n"
        "Отправь фото — я поставлю задачу в очередь и подготовлю результат.\n"
        "Команды: /help, /status"
    )


@router.message(Command("help"))
async def on_help(message: Message) -> None:
    await message.answer(
        "MVP-бот:\n"
        "1) Принимает фото.\n"
        "2) Сохраняет оригинал в storage/raw/<user_id>/.\n"
        "3) Создаёт job в SQLite и обрабатывает в фоне."
    )


@router.message(Command("status"))
async def on_status(message: Message, app_ctx: AppContext) -> None:
    user_id = message.from_user.id
    with app_ctx.session_factory() as session:
        repo = NeuroPhotoshootRepo(session)
        jobs = repo.get_user_jobs(user_id=user_id, limit=5)

    if not jobs:
        await message.answer("У вас пока нет задач.")
        return

    lines = [f"job#{job.id}: {job.status}" for job in jobs]
    await message.answer("Последние задачи:\n" + "\n".join(lines))


@router.message(F.photo)
async def on_photo(message: Message, bot: Bot, app_ctx: AppContext) -> None:
    user_id = message.from_user.id

    with app_ctx.session_factory() as session:
        repo = NeuroPhotoshootRepo(session)
        if repo.count_user_photos(user_id) >= app_ctx.settings.max_photos_per_user:
            await message.answer("Достигнут лимит фотографий для вашего аккаунта.")
            return

        if repo.count_active_jobs(user_id) >= app_ctx.settings.max_concurrent_jobs_per_user:
            await message.answer("Слишком много активных задач. Дождитесь завершения текущих.")
            return

    largest_photo = message.photo[-1]
    telegram_file = await bot.get_file(largest_photo.file_id)
    destination = app_ctx.storage.build_raw_photo_path(user_id=user_id, extension=".jpg")
    await bot.download(telegram_file, destination=destination)

    with app_ctx.session_factory() as session:
        repo = NeuroPhotoshootRepo(session)
        photo = repo.create_uploaded_photo(user_id=user_id, telegram_file_id=largest_photo.file_id, local_path=str(destination))
        job = repo.create_job(user_id=user_id, photo_id=photo.id)

    await app_ctx.queue.put((job.id, user_id, destination))
    await message.answer(f"Фото принято. Задача #{job.id} добавлена в очередь.")


async def worker_loop(app_ctx: AppContext) -> None:
    logger.info("Worker started")
    while True:
        job_id, user_id, source_path = await app_ctx.queue.get()
        try:
            with app_ctx.session_factory() as session:
                NeuroPhotoshootRepo(session).set_job_status(job_id, JobStatus.processing)

            result_path = app_ctx.storage.build_result_path(user_id=user_id, job_id=job_id)
            result_path.write_bytes(source_path.read_bytes())

            with app_ctx.session_factory() as session:
                NeuroPhotoshootRepo(session).set_job_status(job_id, JobStatus.done, result_path=str(result_path))

            logger.info("Job completed", extra={"job_id": job_id, "user_id": user_id})
        except Exception as exc:  # noqa: BLE001
            logger.exception("Job failed", extra={"job_id": job_id, "user_id": user_id})
            with app_ctx.session_factory() as session:
                NeuroPhotoshootRepo(session).set_job_status(job_id, JobStatus.failed, error_message=str(exc))
        finally:
            app_ctx.queue.task_done()


async def main() -> None:
    settings = get_settings()
    setup_logging(settings.log_level)

    storage = LocalStorage(settings.storage_dir)
    storage.ensure_dirs()

    session_factory = create_session_factory(settings)
    with session_factory() as session:
        Base.metadata.create_all(bind=session.bind)

    app_ctx = AppContext(settings=settings, session_factory=session_factory, storage=storage)
    app_ctx.worker_task = asyncio.create_task(worker_loop(app_ctx))

    bot = Bot(settings.telegram_bot_token)
    dp = Dispatcher()
    dp.include_router(router)
    dp["app_ctx"] = app_ctx

    logger.info("Starting bot polling")
    try:
        await dp.start_polling(bot)
    finally:
        if app_ctx.worker_task:
            app_ctx.worker_task.cancel()
            with suppress(asyncio.CancelledError):
                await app_ctx.worker_task
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
