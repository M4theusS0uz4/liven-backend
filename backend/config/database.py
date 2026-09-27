from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from config.config import env


class Base(DeclarativeBase):
    """Base compartilhada pelos modelos persistidos no PostgreSQL."""


database_url = env["DATABASE_URL"]
connect_args = {"connect_timeout": 5} if database_url.startswith("postgresql") else {}
engine = create_engine(database_url, connect_args=connect_args, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
