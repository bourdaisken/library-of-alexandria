"""SQLAlchemy engine/session. Connection forced to UTF-8 client encoding."""
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, scoped_session

from .config import Config

# client_encoding=utf8 makes the encoding guarantee explicit on the wire.
engine = create_engine(
    Config.DATABASE_URL,
    future=True,
    pool_pre_ping=True,
    connect_args={"client_encoding": "utf8"},
)

SessionFactory = sessionmaker(bind=engine, autoflush=False, future=True)
Session = scoped_session(SessionFactory)


def init_db():
    """Create all tables. (Alembic migrations are the path for production schema changes.)"""
    from .models import Base
    Base.metadata.create_all(engine)
