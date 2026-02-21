from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import Generation, Job, JobStatus, PhotoAsset, PhotoKind, Profile, ScenePrompt, ShootSettings, User


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

    def upsert_profile(self, user_id: int, profile_text: str, age: int | None, height_cm: int | None, weight_kg: int | None) -> Profile:
        stmt = select(Profile).where(Profile.user_id == user_id)
        profile = self.session.scalar(stmt)
        if profile is None:
            profile = Profile(
                user_id=user_id,
                profile_text=profile_text,
                age=age,
                height_cm=height_cm,
                weight_kg=weight_kg,
            )
            self.session.add(profile)
        else:
            profile.profile_text = profile_text
            profile.age = age
            profile.height_cm = height_cm
            profile.weight_kg = weight_kg
        self.session.commit()
        self.session.refresh(profile)
        return profile

    def get_profile(self, user_id: int) -> Profile | None:
        return self.session.scalar(select(Profile).where(Profile.user_id == user_id))

    def count_photos(self, user_id: int, kind: PhotoKind) -> int:
        stmt = select(func.count(PhotoAsset.id)).where(PhotoAsset.user_id == user_id, PhotoAsset.kind == kind)
        return int(self.session.execute(stmt).scalar_one())

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

    def create_job(self, user_id: int) -> Job:
        job = Job(user_id=user_id, status=JobStatus.QUEUED)
        self.session.add(job)
        self.session.commit()
        self.session.refresh(job)
        return job

    def get_generations(self, user_id: int, limit: int = 10) -> list[Generation]:
        stmt = select(Generation).where(Generation.user_id == user_id).order_by(Generation.created_at.desc()).limit(limit)
        return list(self.session.scalars(stmt).all())

    def get_generation(self, generation_id: int, user_id: int) -> Generation | None:
        stmt = select(Generation).where(Generation.id == generation_id, Generation.user_id == user_id)
        return self.session.scalar(stmt)
