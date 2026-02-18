import uuid

from aiogram import F, Router
from aiogram.types import CallbackQuery
from arq.connections import RedisSettings, create_pool
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.services.account_service import AccountService
from app.services.credit_service import InsufficientCreditsError, WorkspaceBusyError
from app.services.generation_service import GenerationService, IdentityNotReadyError
from app.services.storage import build_storage
from app.services.template_service import TemplateService

router = Router()


@router.callback_query(F.data.startswith("tpl:"))
async def choose_template(callback: CallbackQuery, session: AsyncSession) -> None:
    code = callback.data.split(":", 1)[1]
    template = await TemplateService(session).get_by_code(code)
    if not template:
        await callback.message.answer("Шаблон не найден")
        await callback.answer()
        return

    user = await AccountService(session).get_or_create_user(callback.from_user.id)
    service = GenerationService(session, build_storage())
    try:
        job = await service.create_generation_job(user, template)
        await session.commit()
    except IdentityNotReadyError:
        await callback.message.answer("Сначала завершите /enroll")
        await callback.answer()
        return
    except InsufficientCreditsError:
        await callback.message.answer("Недостаточно кредитов")
        await callback.answer()
        return
    except WorkspaceBusyError:
        await callback.message.answer("Слишком много активных задач, подождите")
        await callback.answer()
        return

    redis = await create_pool(RedisSettings.from_dsn(get_settings().redis_url))
    await redis.enqueue_job("process_generate_job", str(job.id), _job_id=f"gen:{uuid.uuid4().hex}")
    await callback.message.answer("Генерация поставлена в очередь")
    await callback.answer("Принято")
