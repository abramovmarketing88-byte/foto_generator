from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import FSInputFile, Message
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.models import Job, JobStatus, ResultAsset, User
from app.services.account_service import AccountService
from app.services.storage import LocalStorage, build_storage

router = Router()


@router.message(Command("results"))
@router.message(F.text == "Мои результаты")
async def cmd_results(message: Message, session: AsyncSession) -> None:
    user = await AccountService(session).get_or_create_user(message.from_user.id)
    stmt = (
        select(ResultAsset)
        .join(Job, ResultAsset.job_id == Job.id)
        .where(Job.workspace_id == user.workspace_id, Job.status == JobStatus.DONE)
        .order_by(ResultAsset.created_at.desc())
        .limit(10)
    )
    assets = list((await session.execute(stmt)).scalars().all())
    if not assets:
        await message.answer("Пока нет результатов")
        return
    storage = build_storage()
    if isinstance(storage, LocalStorage):
        for asset in assets[:3]:
            await message.answer_photo(FSInputFile(f"{storage.root}/{asset.storage_key}"))
    else:
        await message.answer("Результаты доступны в S3 storage")
