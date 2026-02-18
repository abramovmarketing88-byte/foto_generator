from __future__ import annotations

from datetime import UTC, datetime

from aiogram import Bot
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from sqlalchemy import select

from app.core.config import get_settings
from app.core.database import AsyncSessionLocal
from app.domain.models import (
    AIBranch,
    AIDialogMessage,
    AIDialogState,
    DialogRoleEnum,
    FollowupContentTypeEnum,
    FollowupSendModeEnum,
    FollowupStep,
    PromptTemplate,
    ScheduledFollowup,
    ScheduledFollowupStatusEnum,
)
from app.integrations.llm_client import LLMClient
from app.services.ai_service import AIService


async def process_followups() -> None:
    settings = get_settings()
    bot = Bot(token=settings.bot_token)
    try:
        async with AsyncSessionLocal() as session:
            rows = list(
                (
                    await session.execute(
                        select(ScheduledFollowup)
                        .where(
                            ScheduledFollowup.status == ScheduledFollowupStatusEnum.pending,
                            ScheduledFollowup.execute_at <= datetime.now(UTC),
                        )
                        .order_by(ScheduledFollowup.execute_at)
                        .limit(100)
                        .with_for_update(skip_locked=True)
                    )
                )
                .scalars()
                .all()
            )

            ai_service = AIService(session)
            llm_client = LLMClient()
            for item in rows:
                try:
                    state = await session.get(
                        AIDialogState,
                        {"user_id": item.user_id, "branch_id": item.branch_id, "dialog_id": item.dialog_id},
                    )
                    step = await session.get(FollowupStep, item.step_id)
                    if step is None:
                        item.status = ScheduledFollowupStatusEnum.failed
                        continue

                    if state:
                        if step.send_mode == FollowupSendModeEnum.if_not_converted and state.is_converted:
                            item.status = ScheduledFollowupStatusEnum.canceled
                            item.converted = True
                            continue
                        if step.send_mode == FollowupSendModeEnum.if_not_converted_and_no_negative and (
                            state.is_converted or state.has_negative
                        ):
                            item.status = ScheduledFollowupStatusEnum.canceled
                            item.converted = state.is_converted
                            item.negative_detected = state.has_negative
                            continue

                    text = step.fixed_text or ""
                    if step.content_type == FollowupContentTypeEnum.llm:
                        branch = await session.get(AIBranch, item.branch_id)
                        prompt = await session.get(PromptTemplate, step.prompt_template_id) if step.prompt_template_id else None
                        if not branch or not prompt:
                            item.status = ScheduledFollowupStatusEnum.failed
                            continue
                        context = await ai_service.get_followup_context_summary(item.user_id, item.branch_id, item.dialog_id)
                        text = await llm_client.generate_followup(branch, prompt, context)

                    await bot.send_message(chat_id=item.user_id, text=text)
                    session.add(
                        AIDialogMessage(
                            user_id=item.user_id,
                            branch_id=item.branch_id,
                            dialog_id=item.dialog_id,
                            role=DialogRoleEnum.assistant,
                            content=text,
                        )
                    )
                    item.status = ScheduledFollowupStatusEnum.sent
                except Exception:
                    item.status = ScheduledFollowupStatusEnum.failed
            await session.commit()
    finally:
        await bot.session.close()


scheduler = AsyncIOScheduler()


def setup_scheduler() -> AsyncIOScheduler:
    if not scheduler.get_jobs():
        scheduler.add_job(process_followups, "interval", seconds=45, max_instances=1, id="process_followups")
    return scheduler
