from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.models import PlanEnum, Workspace
from app.services.credit_service import CreditService
from app.services.payments_service import PaymentsService


class AdminService:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def grant_credits(self, workspace_id, amount: int) -> Workspace:
        service = CreditService(self.session)
        workspace = await service.grant_credits(workspace_id, amount)
        await PaymentsService(self.session).record_admin_credit_purchase(workspace_id, amount)
        await self.session.commit()
        return workspace

    async def set_plan(self, workspace_id, plan: str) -> Workspace:
        workspace = await self.session.get(Workspace, workspace_id)
        if not workspace:
            raise ValueError("Workspace not found")
        workspace.plan = PlanEnum(plan)
        await self.session.commit()
        return workspace
