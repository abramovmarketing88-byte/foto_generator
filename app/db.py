from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.config import Settings


def create_session_factory(settings: Settings) -> sessionmaker[Session]:
    connect_args = {}
    if settings.database_url.startswith("sqlite"):
        connect_args = {"check_same_thread": False}

    engine = create_engine(settings.database_url, pool_pre_ping=True, connect_args=connect_args)
    return sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
