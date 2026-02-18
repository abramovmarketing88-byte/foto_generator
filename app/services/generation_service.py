import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.models import Identity, IdentityStatus, Job, JobStatus, JobType, ResultAsset, Template, User
from app.services.credit_service import CreditService
from app.services.storage import BaseStorage


class IdentityNotReadyError(Exception):
    pass


class GenerationService:
    def __init__(self, session: AsyncSession, storage: BaseStorage) -> None:
        self.session = session
        self.storage = storage

    async def latest_ready_identity(self, workspace_id):
        stmt = (
            select(Identity)
            .where(Identity.workspace_id == workspace_id, Identity.status == IdentityStatus.READY)
            .order_by(Identity.created_at.desc())
        )
        return (await self.session.execute(stmt)).scalars().first()

    async def create_generation_job(self, user: User, template: Template) -> Job:
        credit_service = CreditService(self.session)
        await credit_service.ensure_capacity(user.workspace_id)
        identity = await self.latest_ready_identity(user.workspace_id)
        if not identity:
            raise IdentityNotReadyError("Identity is not ready")

        await credit_service.spend_credits(user.workspace_id, template.cost_credits)
        job = Job(
            workspace_id=user.workspace_id,
            user_id=user.id,
            identity_id=identity.id,
            template_id=template.id,
            type=JobType.GENERATE,
            status=JobStatus.QUEUED,
        )
        self.session.add(job)
        await self.session.flush()
        return job

    async def save_result_assets(self, job_id, assets: list[bytes]) -> list[ResultAsset]:
        saved: list[ResultAsset] = []
        for idx, blob in enumerate(assets, start=1):
            key = f"results/{job_id}/{idx}-{uuid.uuid4().hex}.jpg"
            storage_key = await self.storage.save_bytes(key=key, content=blob, mime_type="image/jpeg")
            entity = ResultAsset(job_id=job_id, storage_key=storage_key, mime_type="image/jpeg", size_bytes=len(blob))
            self.session.add(entity)
            saved.append(entity)
        await self.session.flush()
        return saved
