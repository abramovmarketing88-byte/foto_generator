import os
from functools import lru_cache
from typing import Optional

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


# Token is loaded from environment only. Supports TELEGRAM_BOT_TOKEN or BOT_TOKEN. No hardcoded values.
class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "NeuroPhotoshoot"
    log_level: str = "INFO"

    telegram_bot_token: str = Field(default="", alias="TELEGRAM_BOT_TOKEN")

    @model_validator(mode="after")
    def resolve_bot_token(self) -> "Settings":
        if not (self.telegram_bot_token and self.telegram_bot_token.strip()):
            fallback = os.getenv("BOT_TOKEN", "").strip()
            if fallback:
                object.__setattr__(self, "telegram_bot_token", fallback)
            else:
                raise ValueError("TELEGRAM_BOT_TOKEN or BOT_TOKEN must be set in environment")
        return self
    gemini_api_key: Optional[str] = Field(default=None, alias="GEMINI_API_KEY")
    gemini_analysis_model: str = Field(default="gemini-2.0-flash", alias="GEMINI_ANALYSIS_MODEL")
    gemini_retries: int = Field(default=3, alias="GEMINI_RETRIES")

    nanobanana_api_key: Optional[str] = Field(default=None, alias="NANOBANANA_API_KEY")
    nanobanana_base_url: str = Field(default="https://api.nanobanana.example", alias="NANOBANANA_BASE_URL")
    nanobanana_generate_path: str = Field(default="/v1/generate", alias="NANOBANANA_GENERATE_PATH")
    nanobanana_timeout_sec: int = Field(default=60, alias="NANOBANANA_TIMEOUT_SEC")
    nanobanana_retries: int = Field(default=5, alias="NANOBANANA_RETRIES")

    job_timeout_sec: int = Field(default=120, alias="JOB_TIMEOUT_SEC")

    database_url: str = Field(..., alias="DATABASE_URL")
    storage_dir: str = Field(default="/data/storage", alias="STORAGE_DIR")

    max_photos_per_user: int = Field(default=20, alias="MAX_PHOTOS_PER_USER")
    max_concurrent_jobs_per_user: int = Field(default=2, alias="MAX_CONCURRENT_JOBS_PER_USER")


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
