import base64
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.models import Identity, IdentityStatus, Job, JobStatus, JobType, User


class EnrollLimitError(Exception):
    pass


class EnrollService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def check_free_enroll_limit(self, workspace_id) -> None:
        stmt = select(Identity).where(Identity.workspace_id == workspace_id)
        existing = (await self.session.execute(stmt)).scalars().first()
        if existing:
            raise EnrollLimitError("Free enroll already used")

    async def create_enroll_job(self, user: User, image_bytes: list[bytes]) -> tuple[Identity, Job, list[str]]:
        identity = Identity(workspace_id=user.workspace_id, status=IdentityStatus.ENROLLING)
        self.session.add(identity)
        await self.session.flush()

        job = Job(
            workspace_id=user.workspace_id,
            user_id=user.id,
            identity_id=identity.id,
            type=JobType.ENROLL,
            status=JobStatus.QUEUED,
        )
        self.session.add(job)
        encoded = [base64.b64encode(b).decode("utf-8") for b in image_bytes]
        return identity, job, encoded

    @staticmethod
    def build_user_tag(tg_user_id: int) -> str:
        return f"tg-{tg_user_id}-{uuid.uuid4().hex[:8]}"
