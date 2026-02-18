from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.models import Workspace
from app.services.account_service import AccountService

router = Router()


@router.message(Command("account"))
@router.message(F.text == "Мои кредиты/подписка")
async def cmd_account(message: Message, session: AsyncSession) -> None:
    user = await AccountService(session).get_or_create_user(message.from_user.id)
    workspace = await session.get(Workspace, user.workspace_id)
    await message.answer(
        f"План: {workspace.plan.value}\nКредиты: {workspace.credits_balance}\n"
        "Покупки: пока через админа. Интеграция Telegram Stars будет в payments-слое."
    )
