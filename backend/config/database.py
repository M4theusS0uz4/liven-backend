from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from config.config import env


class Base(DeclarativeBase):
    """Base compartilhada pelos modelos persistidos no PostgreSQL."""


engine = create_engine(env["DATABASE_URL"], pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
