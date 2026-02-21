from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "NeuroPhotoshoot"
    log_level: str = "INFO"

    telegram_bot_token: str = Field(..., alias="TELEGRAM_BOT_TOKEN")
    gemini_api_key: str = Field(..., alias="GEMINI_API_KEY")
    nanobanana_api_key: str = Field(..., alias="NANOBANANA_API_KEY")

    database_url: str = Field(default="sqlite+pysqlite:///./storage/neurophotoshoot.db", alias="DATABASE_URL")
    storage_dir: str = Field(default="./storage", alias="STORAGE_DIR")

    max_photos_per_user: int = Field(default=20, alias="MAX_PHOTOS_PER_USER")
    max_concurrent_jobs_per_user: int = Field(default=2, alias="MAX_CONCURRENT_JOBS_PER_USER")


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
