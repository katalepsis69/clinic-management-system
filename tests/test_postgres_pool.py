from unittest.mock import patch
from app.database import create_db_engine
from app.config import Settings

def test_engine_pool_configuration():
    settings = Settings(
        DATABASE_URL="sqlite:///./test.db",
        SECRET_KEY="a-very-strong-secret-key-for-prod-testing-12345",
        DEMO_MODE=False
    )
    engine = create_db_engine(settings)
    assert engine is not None

def test_engine_postgres_pool_arguments():
    settings = Settings(
        DATABASE_URL="postgresql+psycopg://user:pass@localhost:5432/clinicdb",
        SECRET_KEY="a-very-strong-secret-key-for-prod-testing-12345",
        DEMO_MODE=False
    )
    with patch("app.database.create_engine") as mock_create_engine:
        create_db_engine(settings)
        mock_create_engine.assert_called_once_with(
            "postgresql+psycopg://user:pass@localhost:5432/clinicdb",
            pool_size=20,
            max_overflow=10,
            pool_timeout=30,
            pool_recycle=1800,
            pool_pre_ping=True,
            connect_args={"sslmode": "require"},
        )
