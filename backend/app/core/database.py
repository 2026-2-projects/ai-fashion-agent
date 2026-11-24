from collections.abc import Iterator

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import DATABASE_URL
from app.core.database_url import postgres_url

engine = create_engine(
    postgres_url(DATABASE_URL, sqlalchemy=True),
    pool_pre_ping=True,
    hide_parameters=True,
)

SessionLocal = sessionmaker(
    bind=engine,
    autoflush=False,
    expire_on_commit=False,
)


def get_db() -> Iterator[Session]:
    with SessionLocal() as session:
        yield session
