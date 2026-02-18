from functools import lru_cache
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    bot_token: str = Field(alias="BOT_TOKEN")
    database_url: str = Field(alias="DATABASE_URL")
    redis_url: str = Field(alias="REDIS_URL")

    nanobanana_base_url: str = Field(alias="NANOBANANA_BASE_URL")
    nanobanana_api_key: str = Field(alias="NANOBANANA_API_KEY")

    admin_user_ids: str = Field(default="", alias="ADMIN_USER_IDS")

    storage_mode: Literal["local", "s3"] = Field(default="local", alias="STORAGE_MODE")
    local_storage_path: str = Field(default="./storage", alias="LOCAL_STORAGE_PATH")

    s3_bucket: str = Field(default="", alias="S3_BUCKET")
    s3_region: str = Field(default="", alias="S3_REGION")
    s3_access_key_id: str = Field(default="", alias="S3_ACCESS_KEY_ID")
    s3_secret_access_key: str = Field(default="", alias="S3_SECRET_ACCESS_KEY")
    s3_endpoint_url: str | None = Field(default=None, alias="S3_ENDPOINT_URL")

    request_timeout_seconds: float = Field(default=20.0, alias="REQUEST_TIMEOUT_SECONDS")

    llm_api_key: str = Field(default="", alias="LLM_API_KEY")
    llm_model_gpt_mini: str = Field(default="gpt-4o-mini", alias="LLM_MODEL_GPT_MINI")
    llm_model_gpt_mid: str = Field(default="gpt-4.1-mini", alias="LLM_MODEL_GPT_MID")
    llm_model_gpt_optimal: str = Field(default="gpt-4.1", alias="LLM_MODEL_GPT_OPTIMAL")
    llm_model_gpt_pro: str = Field(default="gpt-4.1", alias="LLM_MODEL_GPT_PRO")

    @property
    def admin_ids(self) -> set[int]:
        return {int(x.strip()) for x in self.admin_user_ids.split(",") if x.strip()}


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()


MODEL_ALIASES = {
    "gpt-mini": "llm_model_gpt_mini",
    "gpt-mid": "llm_model_gpt_mid",
    "gpt-optimal": "llm_model_gpt_optimal",
    "gpt-pro": "llm_model_gpt_pro",
}


def resolve_model_alias(alias: str) -> str:
    settings = get_settings()
    key = MODEL_ALIASES.get(alias)
    if not key:
        return alias
    return getattr(settings, key)
