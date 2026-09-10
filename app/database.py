import os
from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker
from app.config import get_settings

def create_db_engine(settings):
    url = settings.DATABASE_URL
    # ponytail: 20-conn pool + pre-ping is standard; upgrade to external pgbouncer if scaling past 500 rps
    if url.startswith("postgresql"):
        connect_args = {"sslmode": "require"} if not settings.DEMO_MODE else {}
        return create_engine(
            url,
            pool_size=20,
            max_overflow=10,
            pool_timeout=30,
            pool_recycle=1800,
            pool_pre_ping=True,
            connect_args=connect_args,
        )
    else:
        connect_args = {"check_same_thread": False} if url.startswith("sqlite") else {}
        if url.startswith("sqlite"):
            db_file_path = url.replace("sqlite:///", "")
            if db_file_path and db_file_path != ":memory:":
                os.makedirs(os.path.dirname(db_file_path) or ".", exist_ok=True)
        return create_engine(url, connect_args=connect_args)

settings = get_settings()
engine = create_db_engine(settings)

# SQLite Concurrency in WAL Mode + Busy Timeout listener
@event.listens_for(Engine, "connect")
def set_sqlite_pragma(dbapi_connection, connection_record):
    if type(dbapi_connection).__module__ == "sqlite3":
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA journal_mode=WAL;")
        cursor.execute("PRAGMA busy_timeout = 5000;")
        cursor.close()

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

class Base(DeclarativeBase):
    pass

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
