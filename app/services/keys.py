from __future__ import annotations

from sqlalchemy.orm import sessionmaker

from app.config import Settings
from app.models import UserKeys


class MissingKeyError(RuntimeError):
    def __init__(self, provider: str):
        super().__init__(f"missing_api_key_for_provider:{provider}")
        self.provider = provider


_settings: Settings | None = None
_session_factory: sessionmaker | None = None


def configure_keys_service(settings: Settings, session_factory: sessionmaker) -> None:
    global _settings, _session_factory
    _settings = settings
    _session_factory = session_factory


async def get_api_key(user_id: int, provider: str) -> str:
    if _settings is None or _session_factory is None:
        raise RuntimeError("keys service is not configured")

    normalized_provider = provider.strip().lower()
    with _session_factory() as session:
        user_keys = session.get(UserKeys, user_id)

    if normalized_provider == "gemini":
        user_key = user_keys.gemini_key if user_keys else None
        key = user_key or _settings.gemini_api_key
    elif normalized_provider == "nanobanana":
        user_key = user_keys.nanobanana_key if user_keys else None
        key = user_key or _settings.nanobanana_api_key
    else:
        raise ValueError(f"unsupported_provider:{provider}")

    if not key:
        raise MissingKeyError(normalized_provider)
    return key
