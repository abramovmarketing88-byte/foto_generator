from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session, aliased

from app.models import Generation, Job, JobStatus, PhotoAsset, PhotoKind, Profile, ScenePrompt, ShootSettings, User, UserKeys
from app.security import encrypt_secret


class NeuroPhotoshootRepo:
    def __init__(self, session: Session):
        self.session = session

    def ensure_user(self, telegram_user_id: int) -> User:
        user = self.get_user_by_telegram_id(telegram_user_id)
        if user:
            return user
        user = User(telegram_user_id=telegram_user_id)
        self.session.add(user)
        self.session.commit()
        self.session.refresh(user)
        return user

    def get_user_by_telegram_id(self, telegram_user_id: int) -> User | None:
        stmt = select(User).where(User.telegram_user_id == telegram_user_id)
        return self.session.scalar(stmt)

    def get_user_by_id(self, user_id: int) -> User | None:
        return self.session.scalar(select(User).where(User.id == user_id))

    def upsert_profile(
        self,
        user_id: int,
        profile_text: str,
        age: int | None = None,
        height_cm: int | None = None,
        weight_kg: int | None = None,
        hair_color: str | None = None,
        eye_color: str | None = None,
        body_type: str | None = None,
    ) -> Profile:
        stmt = select(Profile).where(Profile.user_id == user_id)
        profile = self.session.scalar(stmt)
        if profile is None:
            profile = Profile(
                user_id=user_id,
                profile_text=profile_text,
                age=age,
                height_cm=height_cm,
                weight_kg=weight_kg,
                hair_color=hair_color,
                eye_color=eye_color,
                body_type=body_type,
            )
            self.session.add(profile)
        else:
            profile.profile_text = profile_text
            if age is not None:
                profile.age = age
            if height_cm is not None:
                profile.height_cm = height_cm
            if weight_kg is not None:
                profile.weight_kg = weight_kg
            if hair_color is not None:
                profile.hair_color = hair_color
            if eye_color is not None:
                profile.eye_color = eye_color
            if body_type is not None:
                profile.body_type = body_type
        self.session.commit()
        self.session.refresh(profile)
        return profile

    def is_profile_complete(self, user_id: int) -> bool:
        """Check if profile has all required physical traits (height, weight, hair, eyes, body type)."""
        profile = self.get_profile(user_id)
        if not profile:
            return False
        return all(
            [
                profile.height_cm is not None,
                profile.weight_kg is not None,
                profile.hair_color,
                profile.eye_color,
                profile.body_type,
            ]
        )

    def get_profile(self, user_id: int) -> Profile | None:
        return self.session.scalar(select(Profile).where(Profile.user_id == user_id))

    def count_photos(self, user_id: int, kind: PhotoKind) -> int:
        stmt = select(func.count(PhotoAsset.id)).where(PhotoAsset.user_id == user_id, PhotoAsset.kind == kind)
        return int(self.session.execute(stmt).scalar_one())

    def list_photos(self, user_id: int, kind: PhotoKind | None = None) -> list[PhotoAsset]:
        stmt = select(PhotoAsset).where(PhotoAsset.user_id == user_id).order_by(PhotoAsset.kind, PhotoAsset.position_index)
        if kind is not None:
            stmt = stmt.where(PhotoAsset.kind == kind)
        return list(self.session.scalars(stmt).all())

    def add_photo(self, user_id: int, kind: PhotoKind, file_path: str) -> PhotoAsset:
        next_pos_stmt = select(func.coalesce(func.max(PhotoAsset.position_index), 0)).where(
            PhotoAsset.user_id == user_id,
            PhotoAsset.kind == kind,
        )
        next_pos = int(self.session.execute(next_pos_stmt).scalar_one()) + 1
        photo = PhotoAsset(user_id=user_id, kind=kind, position_index=next_pos, file_path=file_path)
        self.session.add(photo)
        self.session.commit()
        self.session.refresh(photo)
        return photo

    def clear_user_photos(self, user_id: int) -> list[str]:
        photos = list(self.session.scalars(select(PhotoAsset).where(PhotoAsset.user_id == user_id)).all())
        file_paths = [p.file_path for p in photos]
        for photo in photos:
            self.session.delete(photo)
        self.session.commit()
        return file_paths

    def upsert_scene(self, user_id: int, scene_text: str) -> ScenePrompt:
        scene = self.session.scalar(select(ScenePrompt).where(ScenePrompt.user_id == user_id))
        if scene is None:
            scene = ScenePrompt(user_id=user_id, scene_text=scene_text)
            self.session.add(scene)
        else:
            scene.scene_text = scene_text
        self.session.commit()
        self.session.refresh(scene)
        return scene

    def get_scene(self, user_id: int) -> ScenePrompt | None:
        return self.session.scalar(select(ScenePrompt).where(ScenePrompt.user_id == user_id))

    def get_or_create_shoot_settings(self, user_id: int) -> ShootSettings:
        settings = self.session.scalar(select(ShootSettings).where(ShootSettings.user_id == user_id))
        if settings is None:
            settings = ShootSettings(user_id=user_id)
            self.session.add(settings)
            self.session.commit()
            self.session.refresh(settings)
        return settings

    def update_shoot_settings(self, user_id: int, **kwargs: object) -> ShootSettings:
        settings = self.get_or_create_shoot_settings(user_id)
        for key, value in kwargs.items():
            setattr(settings, key, value)
        self.session.commit()
        self.session.refresh(settings)
        return settings

    def count_active_jobs(self, user_id: int) -> int:
        stmt = select(func.count(Job.id)).where(Job.user_id == user_id, Job.status.in_([JobStatus.QUEUED, JobStatus.RUNNING]))
        return int(self.session.execute(stmt).scalar_one())

    def count_running_jobs(self, user_id: int) -> int:
        stmt = select(func.count(Job.id)).where(Job.user_id == user_id, Job.status == JobStatus.RUNNING)
        return int(self.session.execute(stmt).scalar_one())

    def create_job(self, user_id: int) -> Job:
        job = Job(user_id=user_id, status=JobStatus.QUEUED)
        self.session.add(job)
        self.session.commit()
        self.session.refresh(job)
        return job


    def list_queued_jobs(self, limit: int = 50) -> list[Job]:
        stmt = select(Job).where(Job.status == JobStatus.QUEUED).order_by(Job.created_at.asc(), Job.id.asc()).limit(limit)
        return list(self.session.scalars(stmt).all())

    def get_job_by_id(self, job_id: int) -> Job | None:
        return self.session.scalar(select(Job).where(Job.id == job_id))

    def mark_job_running(self, job_id: int) -> Job | None:
        job = self.session.scalar(select(Job).where(Job.id == job_id))
        if not job:
            return None
        job.status = JobStatus.RUNNING
        job.error = None
        self.session.commit()
        self.session.refresh(job)
        return job

    def claim_next_queued_job(self, max_running_per_user: int) -> Job | None:
        queued_job = aliased(Job)
        running_jobs_for_user = (
            select(func.count(Job.id))
            .where(Job.user_id == queued_job.user_id, Job.status == JobStatus.RUNNING)
            .scalar_subquery()
        )
        claim_stmt = (
            select(queued_job)
            .where(
                queued_job.status == JobStatus.QUEUED,
                running_jobs_for_user < max_running_per_user,
            )
            .order_by(queued_job.created_at.asc(), queued_job.id.asc())
            .limit(1)
            .with_for_update(skip_locked=True)
        )

        with self.session.begin():
            job = self.session.scalar(claim_stmt)
            if not job:
                return None
            job.status = JobStatus.RUNNING
            job.error = None
            self.session.flush()
            self.session.refresh(job)
            return job

    def mark_job_succeeded(self, job_id: int) -> Job | None:
        job = self.session.scalar(select(Job).where(Job.id == job_id))
        if not job:
            return None
        job.status = JobStatus.SUCCEEDED
        job.error = None
        self.session.commit()
        self.session.refresh(job)
        return job

    def mark_job_failed(self, job_id: int, error: str) -> Job | None:
        job = self.session.scalar(select(Job).where(Job.id == job_id))
        if not job:
            return None
        job.status = JobStatus.FAILED
        job.error = error
        self.session.commit()
        self.session.refresh(job)
        return job

    def fail_running_jobs_on_startup(self, error: str) -> int:
        jobs = list(self.session.scalars(select(Job).where(Job.status == JobStatus.RUNNING)).all())
        for job in jobs:
            job.status = JobStatus.FAILED
            job.error = error
        self.session.commit()
        return len(jobs)

    def create_generation(self, user_id: int, job_id: int, final_prompt: str, result_file_path: str) -> Generation:
        generation = Generation(user_id=user_id, job_id=job_id, final_prompt=final_prompt, result_file_path=result_file_path)
        self.session.add(generation)
        self.session.commit()
        self.session.refresh(generation)
        return generation

    def get_generations(self, user_id: int, limit: int = 10) -> list[Generation]:
        stmt = select(Generation).where(Generation.user_id == user_id).order_by(Generation.created_at.desc()).limit(limit)
        return list(self.session.scalars(stmt).all())

    def get_generation(self, generation_id: int, user_id: int) -> Generation | None:
        stmt = select(Generation).where(Generation.id == generation_id, Generation.user_id == user_id)
        return self.session.scalar(stmt)

    def get_user_keys(self, user_id: int) -> UserKeys | None:
        return self.session.get(UserKeys, user_id)

    def get_or_create_user_keys(self, user_id: int) -> UserKeys:
        user_keys = self.get_user_keys(user_id)
        if user_keys is None:
            user_keys = UserKeys(user_id=user_id, active_provider="google")
            self.session.add(user_keys)
        return user_keys

    def upsert_gemini_key(self, user_id: int, key: str) -> UserKeys:
        user_keys = self.get_or_create_user_keys(user_id)
        user_keys.gemini_key = key
        self.session.commit()
        self.session.refresh(user_keys)
        return user_keys

    def upsert_nanobanana_key(self, user_id: int, key: str) -> UserKeys:
        user_keys = self.get_or_create_user_keys(user_id)
        user_keys.nanobanana_key = key
        self.session.commit()
        self.session.refresh(user_keys)
        return user_keys

    def upsert_openrouter_key(self, user_id: int, key: str) -> UserKeys:
        user_keys = self.get_or_create_user_keys(user_id)
        user_keys.openrouter_key = encrypt_secret(key)
        self.session.commit()
        self.session.refresh(user_keys)
        return user_keys

    def set_active_provider(self, user_id: int, provider: str) -> UserKeys:
        normalized = provider.strip().lower()
        if normalized not in {"google", "openrouter"}:
            raise ValueError(f"unsupported_provider:{provider}")
        user_keys = self.get_or_create_user_keys(user_id)
        user_keys.active_provider = normalized
        self.session.commit()
        self.session.refresh(user_keys)
        return user_keys

    def get_active_provider(self, user_id: int) -> str:
        user_keys = self.get_user_keys(user_id)
        if not user_keys or not user_keys.active_provider:
            return "google"
        return user_keys.active_provider
