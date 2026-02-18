import json
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.models import Template


class TemplateService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def list_active(self) -> list[Template]:
        res = await self.session.execute(select(Template).where(Template.is_active.is_(True)).order_by(Template.created_at))
        return list(res.scalars().all())

    async def get_by_code(self, code: str) -> Template | None:
        res = await self.session.execute(select(Template).where(Template.code == code, Template.is_active.is_(True)))
        return res.scalar_one_or_none()


async def seed_templates(session: AsyncSession, seed_path: str = "app/domain/seed_templates.json") -> None:
    data = json.loads(Path(seed_path).read_text(encoding="utf-8"))
    for item in data:
        res = await session.execute(select(Template).where(Template.code == item["code"]))
        existing = res.scalar_one_or_none()
        if existing:
            continue
        session.add(Template(**item))
    await session.commit()
