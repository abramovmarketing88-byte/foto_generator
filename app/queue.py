from __future__ import annotations

from sqlalchemy.orm import sessionmaker

from app.models import Job
from app.repo import NeuroPhotoshootRepo


class JobQueue:
    def __init__(self, session_factory: sessionmaker):
        self._session_factory = session_factory

    def fail_running_jobs_on_startup(self, error: str = "service restart") -> int:
        with self._session_factory() as session:
            return NeuroPhotoshootRepo(session).fail_running_jobs_on_startup(error)

    def pop_next_job(self, max_running_per_user: int) -> Job | None:
        with self._session_factory() as session:
            return NeuroPhotoshootRepo(session).claim_next_queued_job(max_running_per_user)
