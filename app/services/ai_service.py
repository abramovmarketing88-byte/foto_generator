from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta

from sqlalchemy import and_, delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.models import (
    AIBranch,
    AIDialogMessage,
    AIDialogState,
    DialogRoleEnum,
    FollowupChain,
    FollowupStartEventEnum,
    FollowupStep,
    PromptScopeEnum,
    PromptTemplate,
    ScheduledFollowup,
    ScheduledFollowupStatusEnum,
)

PHONE_RE = re.compile(r"(?:\+?7|8)?[\s\-\(]*\d{3}[\s\-\)]*\d{3}[\s\-]*\d{2}[\s\-]*\d{2}")
NEGATIVE_TRIGGERS = ["не интересно", "не надо", "отписка", "хватит", "достали", "спам", "отстаньте"]


class AIService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def list_branches(self, owner_tg_id: int) -> list[AIBranch]:
        return list((await self.session.execute(select(AIBranch).where(AIBranch.owner_id == owner_tg_id))).scalars().all())

    async def get_branch(self, branch_id: int) -> AIBranch | None:
        return await self.session.get(AIBranch, branch_id)

    async def get_system_prompt(self, branch: AIBranch) -> str | None:
        if not branch.system_prompt_id:
            return None
        prompt = await self.session.get(PromptTemplate, branch.system_prompt_id)
        return prompt.content if prompt else None

    async def save_message(self, user_id: int, branch_id: int, role: DialogRoleEnum, content: str, dialog_id: str = "default") -> AIDialogMessage:
        m = AIDialogMessage(user_id=user_id, branch_id=branch_id, dialog_id=dialog_id, role=role, content=content)
        self.session.add(m)
        await self.session.flush()
        return m

    async def upsert_dialog_state(self, user_id: int, branch_id: int, content: str, dialog_id: str = "default") -> tuple[AIDialogState, bool]:
        state = await self.session.get(AIDialogState, {"user_id": user_id, "branch_id": branch_id, "dialog_id": dialog_id})
        is_new = state is None
        if not state:
            state = AIDialogState(user_id=user_id, branch_id=branch_id, dialog_id=dialog_id)
            self.session.add(state)
        state.last_client_message_at = datetime.now(UTC)

        phone_match = PHONE_RE.search(content)
        if phone_match:
            state.is_converted = True
            state.phone_number = phone_match.group(0)

        lower = content.lower()
        if any(trigger in lower for trigger in NEGATIVE_TRIGGERS):
            state.has_negative = True
            await self.session.execute(
                delete(ScheduledFollowup).where(
                    ScheduledFollowup.user_id == user_id,
                    ScheduledFollowup.branch_id == branch_id,
                    ScheduledFollowup.dialog_id == dialog_id,
                    ScheduledFollowup.status == ScheduledFollowupStatusEnum.pending,
                )
            )

        await self.session.flush()
        return state, is_new

    async def build_context_messages(self, branch: AIBranch, dialog_id: str = "default") -> list[dict[str, str]]:
        stmt = select(AIDialogMessage).where(
            AIDialogMessage.user_id == branch.owner_id,
            AIDialogMessage.branch_id == branch.id,
            AIDialogMessage.dialog_id == dialog_id,
        )
        if branch.context_retention_days:
            border = datetime.now(UTC) - timedelta(days=branch.context_retention_days)
            stmt = stmt.where(AIDialogMessage.created_at >= border)
        stmt = stmt.order_by(AIDialogMessage.created_at.desc())
        if branch.max_messages_in_context:
            stmt = stmt.limit(branch.max_messages_in_context)
        rows = list((await self.session.execute(stmt)).scalars().all())
        rows.reverse()
        return [{"role": msg.role.value, "content": msg.content} for msg in rows if msg.role in (DialogRoleEnum.user, DialogRoleEnum.assistant)]

    async def schedule_dialog_started_followups(self, user_id: int, branch: AIBranch, dialog_id: str = "default") -> None:
        if not branch.followup_enabled:
            return
        chain = (
            await self.session.execute(
                select(FollowupChain).where(
                    FollowupChain.branch_id == branch.id,
                    FollowupChain.is_active.is_(True),
                    FollowupChain.start_event == FollowupStartEventEnum.dialog_started,
                )
            )
        ).scalar_one_or_none()
        if not chain:
            return
        steps = list((await self.session.execute(select(FollowupStep).where(FollowupStep.chain_id == chain.id))).scalars().all())
        now = datetime.now(UTC)
        for step in steps:
            self.session.add(
                ScheduledFollowup(
                    user_id=user_id,
                    branch_id=branch.id,
                    chain_id=chain.id,
                    step_id=step.id,
                    dialog_id=dialog_id,
                    execute_at=now + timedelta(seconds=step.delay_seconds),
                    status=ScheduledFollowupStatusEnum.pending,
                )
            )
        await self.session.flush()

    async def list_prompts(self, owner_id: int):
        return list((await self.session.execute(select(PromptTemplate).where(PromptTemplate.owner_id == owner_id))).scalars().all())

    async def get_followup_context_summary(self, user_id: int, branch_id: int, dialog_id: str) -> str:
        msgs = list(
            (
                await self.session.execute(
                    select(AIDialogMessage)
                    .where(
                        AIDialogMessage.user_id == user_id,
                        AIDialogMessage.branch_id == branch_id,
                        AIDialogMessage.dialog_id == dialog_id,
                    )
                    .order_by(AIDialogMessage.created_at.desc())
                    .limit(6)
                )
            )
            .scalars()
            .all()
        )
        msgs.reverse()
        return "\n".join([f"{m.role.value}: {m.content}" for m in msgs])
