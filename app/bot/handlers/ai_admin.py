from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.keyboards import prompts_scope_keyboard
from app.bot.states import PromptCreateStates
from app.core.config import get_settings
from app.domain.models import (
    AIBranch,
    FollowupChain,
    FollowupContentTypeEnum,
    FollowupSendModeEnum,
    FollowupStartEventEnum,
    FollowupStep,
    FollowupTargetChannelEnum,
    GptModelEnum,
    PromptScopeEnum,
    PromptTemplate,
)
from app.services.account_service import AccountService

router = Router()


def _is_admin(user_id: int) -> bool:
    return user_id in get_settings().admin_ids


@router.message(Command("prompts"))
async def prompts_list(message: Message, session: AsyncSession) -> None:
    if not _is_admin(message.from_user.id):
        return
    rows = list((await session.execute(select(PromptTemplate).where(PromptTemplate.owner_id == message.from_user.id))).scalars().all())
    if not rows:
        await message.answer("Промптов нет. /prompt_add")
        return
    text = "\n".join([f"#{r.id} [{r.scope.value}] {r.name}" for r in rows])
    await message.answer(text)


@router.message(Command("prompt_add"))
async def prompt_add(message: Message, state: FSMContext) -> None:
    if not _is_admin(message.from_user.id):
        return
    await state.set_state(PromptCreateStates.waiting_scope)
    await message.answer("Выберите scope:", reply_markup=prompts_scope_keyboard())


@router.callback_query(F.data.startswith("ai_prompt:scope:"), PromptCreateStates.waiting_scope)
async def prompt_scope(callback: CallbackQuery, state: FSMContext) -> None:
    scope = callback.data.split(":")[-1]
    await state.update_data(scope=scope)
    await state.set_state(PromptCreateStates.waiting_name)
    await callback.message.answer("Введите имя промпта")
    await callback.answer()


@router.message(PromptCreateStates.waiting_name)
async def prompt_name(message: Message, state: FSMContext) -> None:
    await state.update_data(name=message.text)
    await state.set_state(PromptCreateStates.waiting_content)
    await message.answer("Отправьте текст или файл .txt/.md")


@router.message(PromptCreateStates.waiting_content)
async def prompt_content(message: Message, state: FSMContext, session: AsyncSession) -> None:
    data = await state.get_data()
    content = message.text or ""
    if message.document:
        doc = message.document
        if not (doc.file_name.endswith(".txt") or doc.file_name.endswith(".md")):
            await message.answer("Нужен .txt/.md файл")
            return
        file = await message.bot.get_file(doc.file_id)
        content = (await message.bot.download_file(file.file_path)).read().decode("utf-8")
    user = await AccountService(session).get_or_create_user(message.from_user.id)
    prompt = PromptTemplate(
        owner_id=user.tg_user_id,
        name=data["name"],
        scope=PromptScopeEnum(data["scope"]),
        content=content,
    )
    session.add(prompt)
    await session.commit()
    await state.clear()
    await message.answer(f"Промпт сохранён #{prompt.id}")


@router.message(Command("prompt_edit"))
async def prompt_edit(message: Message, session: AsyncSession) -> None:
    if not _is_admin(message.from_user.id):
        return
    # /prompt_edit id new content
    parts = message.text.split(maxsplit=2)
    if len(parts) < 3:
        await message.answer("Usage: /prompt_edit <id> <new_content>")
        return
    prompt = await session.get(PromptTemplate, int(parts[1]))
    if not prompt:
        await message.answer("Not found")
        return
    prompt.content = parts[2]
    await session.commit()
    await message.answer("Updated")


@router.message(Command("prompt_delete"))
async def prompt_delete(message: Message, session: AsyncSession) -> None:
    if not _is_admin(message.from_user.id):
        return
    parts = message.text.split(maxsplit=1)
    if len(parts) < 2:
        await message.answer("Usage: /prompt_delete <id>")
        return
    await session.execute(delete(PromptTemplate).where(PromptTemplate.id == int(parts[1])))
    await session.commit()
    await message.answer("Deleted")


@router.message(Command("ai_branches"))
async def branches_list(message: Message, session: AsyncSession) -> None:
    if not _is_admin(message.from_user.id):
        return
    rows = list((await session.execute(select(AIBranch).where(AIBranch.owner_id == message.from_user.id))).scalars().all())
    if not rows:
        await message.answer("Веток нет. Используйте /ai_branch_add")
        return
    await message.answer("\n".join([f"#{b.id} {b.name} ({b.gpt_model.value}) followup={b.followup_enabled}" for b in rows]))


@router.message(Command("ai_branch_add"))
async def ai_branch_add(message: Message, session: AsyncSession) -> None:
    if not _is_admin(message.from_user.id):
        return
    # /ai_branch_add name|model|system_prompt_id|retention|max|followup_enabled|avito_profile_id(optional)
    payload = message.text.replace('/ai_branch_add ', '', 1)
    parts = payload.split('|')
    if len(parts) < 6:
        await message.answer("Usage: /ai_branch_add name|model|system_prompt_id|retention|max|followup_enabled|[avito_profile_uuid]")
        return
    user = await AccountService(session).get_or_create_user(message.from_user.id)
    branch = AIBranch(
        owner_id=user.tg_user_id,
        name=parts[0].strip(),
        gpt_model=GptModelEnum(parts[1].strip()),
        system_prompt_id=int(parts[2].strip()) if parts[2].strip() else None,
        context_retention_days=int(parts[3].strip()) if parts[3].strip() else None,
        max_messages_in_context=int(parts[4].strip()) if parts[4].strip() else None,
        followup_enabled=parts[5].strip().lower() == 'true',
        avito_profile_id=parts[6].strip() if len(parts) > 6 and parts[6].strip() else None,
    )
    session.add(branch)
    await session.commit()
    await message.answer(f"Ветка создана #{branch.id}")


@router.message(Command("ai_branch_delete"))
async def ai_branch_delete(message: Message, session: AsyncSession) -> None:
    if not _is_admin(message.from_user.id):
        return
    parts = message.text.split(maxsplit=1)
    if len(parts) < 2:
        await message.answer("Usage: /ai_branch_delete <id>")
        return
    await session.execute(delete(AIBranch).where(AIBranch.id == int(parts[1])))
    await session.commit()
    await message.answer("Ветка удалена")


@router.message(Command("followups"))
async def followups_list(message: Message, session: AsyncSession) -> None:
    if not _is_admin(message.from_user.id):
        return
    chains = list((await session.execute(select(FollowupChain))).scalars().all())
    if not chains:
        await message.answer("Цепочек нет. /followup_chain_add")
        return
    lines = []
    for c in chains:
        steps = list((await session.execute(select(FollowupStep).where(FollowupStep.chain_id == c.id))).scalars().all())
        lines.append(f"#{c.id} {c.name} branch={c.branch_id} steps={len(steps)}")
    await message.answer("\n".join(lines))


@router.message(Command("followup_chain_add"))
async def followup_chain_add(message: Message, session: AsyncSession) -> None:
    if not _is_admin(message.from_user.id):
        return
    # /followup_chain_add branch_id|name|start_event|is_active|stop_on_conversion
    payload = message.text.replace('/followup_chain_add ', '', 1)
    parts = payload.split('|')
    if len(parts) < 5:
        await message.answer("Usage: /followup_chain_add branch_id|name|dialog_started|true|true")
        return
    chain = FollowupChain(
        branch_id=int(parts[0]),
        name=parts[1],
        start_event=FollowupStartEventEnum(parts[2]),
        is_active=parts[3].lower() == 'true',
        stop_on_conversion=parts[4].lower() == 'true',
    )
    session.add(chain)
    await session.commit()
    await message.answer(f"Chain created #{chain.id}")


@router.message(Command("followup_step_add"))
async def followup_step_add(message: Message, session: AsyncSession) -> None:
    if not _is_admin(message.from_user.id):
        return
    # /followup_step_add chain|order|delay|send_mode|content_type|target_channel|fixed_text_or_prompt_id
    payload = message.text.replace('/followup_step_add ', '', 1)
    parts = payload.split('|')
    if len(parts) < 7:
        await message.answer("Usage: /followup_step_add chain|1|120|if_not_converted|fixed|telegram_user|text OR prompt_id")
        return
    content_type = FollowupContentTypeEnum(parts[4])
    step = FollowupStep(
        chain_id=int(parts[0]),
        order_index=int(parts[1]),
        delay_seconds=int(parts[2]),
        send_mode=FollowupSendModeEnum(parts[3]),
        content_type=content_type,
        fixed_text=parts[6] if content_type == FollowupContentTypeEnum.fixed else None,
        prompt_template_id=int(parts[6]) if content_type == FollowupContentTypeEnum.llm else None,
        target_channel=FollowupTargetChannelEnum(parts[5]),
    )
    session.add(step)
    await session.commit()
    await message.answer(f"Step created #{step.id}")


@router.message(Command("followup_chain_delete"))
async def followup_chain_delete(message: Message, session: AsyncSession) -> None:
    if not _is_admin(message.from_user.id):
        return
    parts = message.text.split(maxsplit=1)
    if len(parts) < 2:
        await message.answer("Usage: /followup_chain_delete <id>")
        return
    await session.execute(delete(FollowupChain).where(FollowupChain.id == int(parts[1])))
    await session.commit()
    await message.answer("Chain deleted")


@router.message(Command("followup_step_delete"))
async def followup_step_delete(message: Message, session: AsyncSession) -> None:
    if not _is_admin(message.from_user.id):
        return
    parts = message.text.split(maxsplit=1)
    if len(parts) < 2:
        await message.answer("Usage: /followup_step_delete <id>")
        return
    await session.execute(delete(FollowupStep).where(FollowupStep.id == int(parts[1])))
    await session.commit()
    await message.answer("Step deleted")
