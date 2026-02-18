from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.services.admin_service import AdminService

router = Router()


def _is_admin(user_id: int) -> bool:
    return user_id in get_settings().admin_ids


@router.message(Command("admin_grant_credits"))
async def admin_grant_credits(message: Message, session: AsyncSession) -> None:
    if not _is_admin(message.from_user.id):
        return
    parts = message.text.split()
    if len(parts) != 3:
        await message.answer("Usage: /admin_grant_credits workspace_id amount")
        return
    workspace_id, amount = parts[1], int(parts[2])
    workspace = await AdminService(session).grant_credits(workspace_id, amount)
    await message.answer(f"Granted. Balance={workspace.credits_balance}")


@router.message(Command("admin_set_plan"))
async def admin_set_plan(message: Message, session: AsyncSession) -> None:
    if not _is_admin(message.from_user.id):
        return
    parts = message.text.split()
    if len(parts) != 3:
        await message.answer("Usage: /admin_set_plan workspace_id FREE|PRO")
        return
    workspace_id, plan = parts[1], parts[2]
    workspace = await AdminService(session).set_plan(workspace_id, plan)
    await message.answer(f"Plan updated: {workspace.plan.value}")
