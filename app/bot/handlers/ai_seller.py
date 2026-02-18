from aiogram import F, Router
from aiogram.filters import CommandStart
from aiogram.types import CallbackQuery, Message
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.keyboards import branches_keyboard, mode_keyboard
from app.domain.models import DialogRoleEnum, ModeEnum, User
from app.integrations.llm_client import LLMClient
from app.services.account_service import AccountService
from app.services.ai_service import AIService

router = Router()


@router.message(CommandStart())
async def start_with_mode(message: Message, session: AsyncSession) -> None:
    await AccountService(session).get_or_create_user(message.from_user.id)
    await message.answer("Выберите режим:", reply_markup=mode_keyboard())


@router.callback_query(F.data.startswith("ai_branch:select:"))
async def select_branch(callback: CallbackQuery, session: AsyncSession) -> None:
    branch_id = int(callback.data.split(":")[-1])
    user = await AccountService(session).get_or_create_user(callback.from_user.id)
    db_user = (await session.execute(select(User).where(User.id == user.id))).scalar_one()
    db_user.current_branch_id = branch_id
    db_user.current_mode = ModeEnum.ai_seller
    await session.commit()
    await callback.message.answer("Ветка выбрана. Пишите сообщение — отвечу как ИИ-продавец.")
    await callback.answer()


@router.callback_query(F.data == "ai_branch:none")
async def no_branch(callback: CallbackQuery) -> None:
    await callback.answer("Сначала создайте ветку через /ai_branches", show_alert=True)


@router.message(F.text, ~F.text.startswith("/"))
async def ai_chat_entry(message: Message, session: AsyncSession) -> None:
    user = await AccountService(session).get_or_create_user(message.from_user.id)
    db_user = (await session.execute(select(User).where(User.id == user.id))).scalar_one()
    if db_user.current_mode != ModeEnum.ai_seller:
        return

    ai_service = AIService(session)
    if not db_user.current_branch_id:
        branches = await ai_service.list_branches(message.from_user.id)
        await message.answer("Выберите ветку:", reply_markup=branches_keyboard([(b.id, b.name) for b in branches]))
        return

    branch = await ai_service.get_branch(db_user.current_branch_id)
    if not branch:
        await message.answer("Ветка не найдена. Выберите снова /mode")
        return

    state, is_new_dialog = await ai_service.upsert_dialog_state(message.from_user.id, branch.id, message.text)
    await ai_service.save_message(message.from_user.id, branch.id, DialogRoleEnum.user, message.text)

    system_prompt = await ai_service.get_system_prompt(branch)
    history = await ai_service.build_context_messages(branch)
    messages = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    messages.extend(history)

    reply = await LLMClient().generate_reply(branch, messages)
    await ai_service.save_message(message.from_user.id, branch.id, DialogRoleEnum.assistant, reply)

    if is_new_dialog:
        await ai_service.schedule_dialog_started_followups(message.from_user.id, branch)

    await session.commit()
    await message.answer(reply)
