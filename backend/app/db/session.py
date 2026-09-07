from typing import Generator

from sqlmodel import Session, create_engine

from app.core.config import settings


def get_engine(database_url: str):
    return create_engine(database_url, pool_pre_ping=True)


engine = get_engine(settings.database_url)


def get_session() -> Generator[Session, None, None]:
    with Session(engine) as session:
        yield session
