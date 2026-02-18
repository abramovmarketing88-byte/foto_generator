import uuid

from aiogram import Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import Message
from arq.connections import RedisSettings, create_pool
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.states import EnrollStates
from app.core.config import get_settings
from app.domain.models import User
from app.services.account_service import AccountService
from app.services.credit_service import CreditService, WorkspaceBusyError
from app.services.enroll_service import EnrollLimitError, EnrollService

router = Router()


@router.message(Command("enroll"))
async def cmd_enroll(message: Message, state: FSMContext) -> None:
    await state.set_state(EnrollStates.waiting_for_photos)
    await state.update_data(photo_file_ids=[])
    await message.answer("Загрузите ровно 5 фото лица (хороший свет, один человек, без очков).")


@router.message(EnrollStates.waiting_for_photos)
async def collect_enroll_photos(message: Message, state: FSMContext, session: AsyncSession) -> None:
    if not message.photo:
        await message.answer("Нужна фотография. Осталось загрузить фото до 5.")
        return

    data = await state.get_data()
    photo_file_ids: list[str] = data.get("photo_file_ids", [])
    photo_file_ids.append(message.photo[-1].file_id)

    if len(photo_file_ids) < 5:
        await state.update_data(photo_file_ids=photo_file_ids)
        await message.answer(f"Принято {len(photo_file_ids)}/5")
        return
    if len(photo_file_ids) > 5:
        await message.answer("Нужно ровно 5 фото. Начните заново: /enroll")
        await state.clear()
        return

    user = await AccountService(session).get_or_create_user(message.from_user.id)
    enroll_service = EnrollService(session)
    credit_service = CreditService(session)
    try:
        await enroll_service.check_free_enroll_limit(user.workspace_id)
        await credit_service.ensure_capacity(user.workspace_id)
    except EnrollLimitError:
        await message.answer("Лимит enroll для Free использован.")
        await state.clear()
        return
    except WorkspaceBusyError:
        await message.answer("Сейчас много задач в работе. Подождите.")
        await state.clear()
        return

    image_blobs: list[bytes] = []
    for file_id in photo_file_ids:
        file = await message.bot.get_file(file_id)
        image_blobs.append((await message.bot.download_file(file.file_path)).read())

    identity, job, encoded = await enroll_service.create_enroll_job(user=user, image_bytes=image_blobs)
    await session.commit()

    redis = await create_pool(RedisSettings.from_dsn(get_settings().redis_url))
    await redis.enqueue_job(
        "process_enroll_job",
        str(job.id),
        encoded,
        enroll_service.build_user_tag(user.tg_user_id),
        _job_id=f"enroll:{uuid.uuid4().hex}",
    )
    await message.answer("Фото приняты. Задача в очереди.")
    await state.clear()
