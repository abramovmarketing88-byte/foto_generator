from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.models import User
from app.services.credit_service import CreditService


class AccountService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_or_create_user(self, tg_user_id: int) -> User:
        existing = (await self.session.execute(select(User).where(User.tg_user_id == tg_user_id))).scalar_one_or_none()
        if existing:
            return existing
        user = User(tg_user_id=tg_user_id)
        self.session.add(user)
        await self.session.flush()
        workspace = await CreditService(self.session).create_default_workspace(owner_user_id=user.id)
        user.workspace_id = workspace.id
        await self.session.commit()
        await self.session.refresh(user)
        return user
