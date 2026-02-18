from __future__ import annotations

import logging
import uuid

from aiogram import Bot
from aiogram.types import BufferedInputFile, InputMediaPhoto
from arq import Retry

from app.core.config import get_settings
from app.core.database import AsyncSessionLocal
from app.domain.models import Identity, IdentityStatus, Job, JobStatus, Template, User
from app.integrations.nanobanana_client import NanoBananaClient
from app.services.generation_service import GenerationService
from app.services.storage import build_storage

logger = logging.getLogger(__name__)
BACKOFF = [1, 5, 15]


def _retry_for_try(job_try: int) -> Retry:
    idx = min(job_try - 1, len(BACKOFF) - 1)
    return Retry(defer=BACKOFF[idx])


async def process_enroll_job(ctx, job_id: str, images_b64: list[str], user_tag: str) -> None:
    client = NanoBananaClient()
    try:
        identity_external = await client.enroll(images_b64, user_tag)
    except Exception as exc:
        if ctx["job_try"] <= 3:
            raise _retry_for_try(ctx["job_try"])
        await _mark_enroll_failed(job_id, str(exc))
        return

    async with AsyncSessionLocal() as session:
        job = await session.get(Job, uuid.UUID(job_id))
        identity = await session.get(Identity, job.identity_id)
        job.status = JobStatus.DONE
        identity.status = IdentityStatus.READY
        identity.identity_id = identity_external
        await session.commit()
        user = await session.get(User, job.user_id)
    await _send_text(user.tg_user_id, "Enroll готов. Теперь выберите шаблон: /templates")


async def _mark_enroll_failed(job_id: str, err: str) -> None:
    async with AsyncSessionLocal() as session:
        job = await session.get(Job, uuid.UUID(job_id))
        identity = await session.get(Identity, job.identity_id)
        user = await session.get(User, job.user_id)
        job.status = JobStatus.FAILED
        job.error_message = err
        identity.status = IdentityStatus.FAILED
        await session.commit()
    await _send_text(user.tg_user_id, "Enroll не удался. Попробуйте снова /enroll")


async def process_generate_job(ctx, job_id: str) -> None:
    client = NanoBananaClient()
    async with AsyncSessionLocal() as session:
        job = await session.get(Job, uuid.UUID(job_id))
        user = await session.get(User, job.user_id)
        job.status = JobStatus.RUNNING
        await session.commit()
    await _send_text(user.tg_user_id, "Делаю ваш креатив...")

    try:
        blobs = await _generate_assets(client, job_id)
    except Exception as exc:
        if ctx["job_try"] <= 3:
            raise _retry_for_try(ctx["job_try"])
        await _mark_generate_failed(job_id, str(exc))
        return

    async with AsyncSessionLocal() as session:
        service = GenerationService(session, build_storage())
        await service.save_result_assets(uuid.UUID(job_id), blobs)
        job = await session.get(Job, uuid.UUID(job_id))
        user = await session.get(User, job.user_id)
        job.status = JobStatus.DONE
        await session.commit()
    await _send_media(user.tg_user_id, blobs)


async def _generate_assets(client: NanoBananaClient, job_id: str) -> list[bytes]:
    async with AsyncSessionLocal() as session:
        job = await session.get(Job, uuid.UUID(job_id))
        identity = await session.get(Identity, job.identity_id)
        template = await session.get(Template, job.template_id)

    result = await client.generate(
        identity_id=identity.identity_id,
        template_code=template.code,
        prompt_override=None,
        width=template.width,
        height=template.height,
        num_outputs=template.num_outputs,
    )

    blobs: list[bytes] = []
    for item in result:
        blobs.append(item if isinstance(item, bytes) else await client.download_url(item))
    return blobs


async def _mark_generate_failed(job_id: str, err: str) -> None:
    async with AsyncSessionLocal() as session:
        job = await session.get(Job, uuid.UUID(job_id))
        user = await session.get(User, job.user_id)
        job.status = JobStatus.FAILED
        job.error_message = err
        await session.commit()
    await _send_text(user.tg_user_id, "Не удалось сгенерировать. Кредит возвращается вручную админом.")


async def _send_text(chat_id: int, text: str) -> None:
    bot = Bot(token=get_settings().bot_token)
    try:
        await bot.send_message(chat_id, text)
    finally:
        await bot.session.close()


async def _send_media(chat_id: int, blobs: list[bytes]) -> None:
    bot = Bot(token=get_settings().bot_token)
    try:
        media = [
            InputMediaPhoto(media=BufferedInputFile(file=b, filename=f"result-{idx}.jpg"))
            for idx, b in enumerate(blobs, start=1)
        ]
        await bot.send_media_group(chat_id, media=media)
        await bot.send_message(chat_id, "Готово ✅")
    finally:
        await bot.session.close()
