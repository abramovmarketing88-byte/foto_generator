from __future__ import annotations

import logging
from urllib.parse import urlparse

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.config import Settings

logger = logging.getLogger(__name__)


def _normalize_database_url(database_url: str) -> str:
    if "+psycopg" in database_url:
        return database_url
    if database_url.startswith("postgresql://"):
        return database_url.replace("postgresql://", "postgresql+psycopg://", 1)
    if database_url.startswith("postgres://"):
        return database_url.replace("postgres://", "postgresql+psycopg://", 1)
    return database_url


def _sanitized_db_target(database_url: str) -> str:
    parsed = urlparse(database_url)
    host = parsed.hostname or "local"
    port = f":{parsed.port}" if parsed.port else ""
    db_name = parsed.path.lstrip("/") or "default"
    return f"{parsed.scheme}://{host}{port}/{db_name}"


def create_session_factory(settings: Settings) -> sessionmaker[Session]:
    raw_database_url = (settings.database_url or "").strip()
    if not raw_database_url:
        raise RuntimeError("DATABASE_URL is required and must not be empty.")

    normalized_database_url = _normalize_database_url(raw_database_url)
    connect_args = {}
    if normalized_database_url.startswith("sqlite"):
        connect_args = {"check_same_thread": False}

    logger.info("Initializing database engine", extra={"database": _sanitized_db_target(normalized_database_url)})

    try:
        engine = create_engine(
            normalized_database_url,
            pool_pre_ping=True,
            pool_recycle=300,
            connect_args=connect_args,
        )
        with engine.connect():
            pass
    except Exception:
        logger.exception("Database initialization error")
        raise

    return sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
