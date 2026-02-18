from arq.connections import RedisSettings

from app.core.config import get_settings
from app.core.logging import configure_logging
from app.workers.tasks import process_enroll_job, process_generate_job

settings = get_settings()


class WorkerSettings:
    functions = [process_enroll_job, process_generate_job]
    redis_settings = RedisSettings.from_dsn(settings.redis_url)
    on_startup = configure_logging
