from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.keyboards import mode_keyboard
from app.domain.models import ModeEnum, User
from app.services.account_service import AccountService
from app.services.ai_service import AIService

router = Router()


@router.message(Command("mode"))
async def cmd_mode(message: Message) -> None:
    await message.answer("Выберите режим:", reply_markup=mode_keyboard())


@router.callback_query(F.data.startswith("ai_mode:"))
async def set_mode(callback: CallbackQuery, session: AsyncSession) -> None:
    mode = callback.data.split(":", 1)[1]
    user = await AccountService(session).get_or_create_user(callback.from_user.id)
    db_user = (await session.execute(select(User).where(User.id == user.id))).scalar_one()
    db_user.current_mode = ModeEnum(mode)
    await session.commit()

    if mode == "ai_seller":
        branches = await AIService(session).list_branches(callback.from_user.id)
        if branches:
            from app.bot.keyboards import branches_keyboard

            await callback.message.answer("Выберите AI-ветку", reply_markup=branches_keyboard([(b.id, b.name) for b in branches]))
        else:
            await callback.message.answer("AI-режим включён. Веток пока нет, создайте через /ai_branches")
    else:
        await callback.message.answer("Режим отчётности включён")
    await callback.answer()
