from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import GenerationJob, JobStatus, UploadedPhoto


class NeuroPhotoshootRepo:
    def __init__(self, session: Session):
        self.session = session

    def count_user_photos(self, user_id: int) -> int:
        stmt = select(func.count(UploadedPhoto.id)).where(UploadedPhoto.user_id == user_id)
        return int(self.session.execute(stmt).scalar_one())

    def create_uploaded_photo(self, user_id: int, telegram_file_id: str, local_path: str) -> UploadedPhoto:
        photo = UploadedPhoto(user_id=user_id, telegram_file_id=telegram_file_id, local_path=local_path)
        self.session.add(photo)
        self.session.commit()
        self.session.refresh(photo)
        return photo

    def create_job(self, user_id: int, photo_id: int) -> GenerationJob:
        job = GenerationJob(user_id=user_id, photo_id=photo_id, status=JobStatus.queued)
        self.session.add(job)
        self.session.commit()
        self.session.refresh(job)
        return job

    def count_active_jobs(self, user_id: int) -> int:
        stmt = select(func.count(GenerationJob.id)).where(
            GenerationJob.user_id == user_id,
            GenerationJob.status.in_([JobStatus.queued, JobStatus.processing]),
        )
        return int(self.session.execute(stmt).scalar_one())

    def set_job_status(self, job_id: int, status: JobStatus, result_path: str | None = None, error_message: str | None = None) -> None:
        job = self.session.get(GenerationJob, job_id)
        if not job:
            return
        job.status = status
        job.result_path = result_path
        job.error_message = error_message
        self.session.commit()

    def get_user_jobs(self, user_id: int, limit: int = 5) -> list[GenerationJob]:
        stmt = (
            select(GenerationJob)
            .where(GenerationJob.user_id == user_id)
            .order_by(GenerationJob.created_at.desc())
            .limit(limit)
        )
        return list(self.session.scalars(stmt).all())
