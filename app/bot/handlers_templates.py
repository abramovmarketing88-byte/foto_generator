from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.keyboards import templates_keyboard
from app.services.template_service import TemplateService

router = Router()


@router.message(Command("templates"))
async def cmd_templates(message: Message, session: AsyncSession) -> None:
    templates = await TemplateService(session).list_active()
    if not templates:
        await message.answer("Пока нет активных шаблонов.")
        return
    lines = [f"{t.code}: {t.title}\n{t.description}" for t in templates]
    await message.answer("\n\n".join(lines), reply_markup=templates_keyboard([t.code for t in templates]))
