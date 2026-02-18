from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.models import Job, JobStatus, PlanEnum, Workspace


class InsufficientCreditsError(Exception):
    pass


class WorkspaceBusyError(Exception):
    pass


class CreditService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create_default_workspace(self, owner_user_id):
        workspace = Workspace(owner_user_id=owner_user_id, plan=PlanEnum.FREE, credits_balance=3)
        self.session.add(workspace)
        await self.session.flush()
        return workspace

    async def ensure_capacity(self, workspace_id) -> None:
        stmt: Select = select(func.count(Job.id)).where(
            Job.workspace_id == workspace_id,
            Job.status.in_([JobStatus.QUEUED, JobStatus.RUNNING]),
        )
        cnt = (await self.session.execute(stmt)).scalar_one()
        if cnt >= 2:
            raise WorkspaceBusyError("Too many active jobs")

    async def spend_credits(self, workspace_id, amount: int) -> None:
        workspace = await self.session.get(Workspace, workspace_id, with_for_update=True)
        if workspace is None or workspace.credits_balance < amount:
            raise InsufficientCreditsError("Not enough credits")
        workspace.credits_balance -= amount
        await self.session.flush()

    async def grant_credits(self, workspace_id, amount: int) -> Workspace:
        workspace = await self.session.get(Workspace, workspace_id, with_for_update=True)
        if workspace is None:
            raise ValueError("Workspace not found")
        workspace.credits_balance += amount
        await self.session.flush()
        return workspace
