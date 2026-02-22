from __future__ import annotations

import asyncio
import logging
from pathlib import Path

from aiogram import Bot
from aiogram.types import BufferedInputFile
from sqlalchemy.orm import sessionmaker

from app.ai.gemini_analyzer import GeminiAnalyzer
from app.ai.nanobanana_client import NanoBananaClient
from app.config import Settings
from app.models import JobStatus, PhotoKind
from app.prompt_builder import build_final_prompt
from app.queue import JobQueue
from app.repo import NeuroPhotoshootRepo
from app.services.keys import MissingKeyError
from app.storage import LocalStorage

logger = logging.getLogger(__name__)


class ReferencePhotosExpiredError(RuntimeError):
    """Raised when photo paths are present in DB, but files are gone on disk."""


def _generation_caption(lens_selected: bool, lens_mm: int | None, angle_code: str, size_code: str) -> str:
    lens_text = f"{lens_mm}mm" if lens_selected and lens_mm else "natural lens"
    return f"Готово!\nЛинза: {lens_text}\nРакурс: {angle_code}\nРазмер: {size_code}"


async def _run_job(
    job_id: int,
    bot: Bot,
    settings: Settings,
    session_factory: sessionmaker,
    storage: LocalStorage,
    gemini: GeminiAnalyzer,
    nanobanana: NanoBananaClient,
) -> None:
    with session_factory() as session:
        repo = NeuroPhotoshootRepo(session)
        job = repo.get_job_by_id(job_id)
        if not job:
            return
        user = repo.get_user_by_id(job.user_id)
        profile = repo.get_profile(job.user_id)
        scene = repo.get_scene(job.user_id)
        shoot_settings = repo.get_or_create_shoot_settings(job.user_id)
        photos = repo.list_photos(job.user_id)

    if not user or not profile or not scene:
        raise RuntimeError("job context is incomplete")

    face_paths = [Path(p.file_path) for p in photos if p.kind == PhotoKind.FACE]
    ref_paths = [Path(p.file_path) for p in photos]
    missing_paths = [str(path) for path in ref_paths if not path.exists()]
    if missing_paths:
        logger.warning(
            "Reference photos are missing on disk",
            extra={"job_id": job_id, "user_id": job.user_id, "missing_paths": missing_paths},
        )
        raise ReferencePhotosExpiredError("reference photos are missing")

    face_bytes = [path.read_bytes() for path in face_paths]
    ref_bytes = [path.read_bytes() for path in ref_paths]

    face_signature_text, warnings = await gemini.analyze_user_photos(user.telegram_user_id, face_bytes)
    if warnings:
        logger.info("Gemini analysis warnings", extra={"job_id": job_id, "warnings_count": len(warnings)})

    final_prompt = build_final_prompt(
        profile_text=profile.profile_text,
        scene_text=scene.scene_text,
        shoot_settings=shoot_settings,
        face_signature_text=face_signature_text,
        photos=photos,
    )
    logger.info("Final prompt built", extra={"job_id": job_id, "prompt": final_prompt})

    image_bytes = await nanobanana.generate_image(user.telegram_user_id, final_prompt, ref_bytes, shoot_settings.output_size_code)

    result_path = storage.build_result_path(job.user_id, job_id, extension=".jpg")
    result_path.write_bytes(image_bytes)

    with session_factory() as session:
        repo = NeuroPhotoshootRepo(session)
        repo.create_generation(job.user_id, job_id, final_prompt, str(result_path))
        repo.mark_job_succeeded(job_id)

    await bot.send_photo(
        chat_id=user.telegram_user_id,
        photo=BufferedInputFile(image_bytes, filename=f"generation_{job_id}.jpg"),
        caption=_generation_caption(
            shoot_settings.lens_selected,
            shoot_settings.lens_mm,
            shoot_settings.angle_code,
            shoot_settings.output_size_code,
        ),
    )


async def run_worker(bot: Bot, settings: Settings, session_factory: sessionmaker, storage: LocalStorage, stop_event: asyncio.Event) -> None:
    queue = JobQueue(session_factory)
    gemini = GeminiAnalyzer(settings)
    nanobanana = NanoBananaClient(settings)

    failed_on_startup = queue.fail_running_jobs_on_startup("service restart")
    if failed_on_startup:
        logger.info("Marked running jobs as failed on startup", extra={"jobs": failed_on_startup})

    while not stop_event.is_set():
        try:
            job = queue.pop_next_job(settings.max_concurrent_jobs_per_user)
            if not job:
                await asyncio.sleep(1.0)
                continue

            with session_factory() as session:
                user = NeuroPhotoshootRepo(session).get_user_by_id(job.user_id)
            if user:
                await bot.send_message(user.telegram_user_id, f"Задача #{job.id}: генерация началась.")

            try:
                await asyncio.wait_for(
                    _run_job(job.id, bot, settings, session_factory, storage, gemini, nanobanana),
                    timeout=settings.job_timeout_sec,
                )
            except Exception as exc:
                error_text = str(exc)[:1000]
                with session_factory() as session:
                    repo = NeuroPhotoshootRepo(session)
                    current_job = repo.get_job_by_id(job.id)
                    if current_job and current_job.status != JobStatus.SUCCEEDED:
                        repo.mark_job_failed(job.id, error_text)
                    user = repo.get_user_by_id(job.user_id)
                if user:
                    if isinstance(exc, MissingKeyError):
                        await bot.send_message(
                            user.telegram_user_id,
                            "⚠️ API Key not found. Please provide your key using /set_gemini or /set_nanobanana.",
                        )
                    elif isinstance(exc, ReferencePhotosExpiredError):
                        await bot.send_message(
                            user.telegram_user_id,
                            "⚠️ Фото из вашей сессии недоступны после перезапуска сервера. "
                            "Пожалуйста, заново загрузите фото в меню «Профиль».",
                        )
                    else:
                        await bot.send_message(user.telegram_user_id, f"Не удалось выполнить генерацию для задачи #{job.id}. Попробуйте позже.")
                logger.exception("Job failed", extra={"job_id": job.id, "user_id": job.user_id})
        except Exception:
            logger.exception("Worker loop error")
            await asyncio.sleep(1.0)
