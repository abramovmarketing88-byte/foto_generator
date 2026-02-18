from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.models import Purchase


class PaymentsService:
    """Abstraction layer for future Telegram Stars integrations."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def record_admin_credit_purchase(self, workspace_id, amount_credits: int, metadata: str = "admin_grant") -> Purchase:
        purchase = Purchase(workspace_id=workspace_id, amount_credits=amount_credits, metadata=metadata)
        self.session.add(purchase)
        await self.session.flush()
        return purchase
