from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    APP_NAME: str = "Clinic Management System"
    SECRET_KEY: str = "dev-secret-key-change-in-production-1234567890"
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 720
    DATABASE_URL: str = "sqlite:///./data/clinic.db"
    DEMO_MODE: bool = True
    GEMINI_API_KEY: str = ""

    model_config = SettingsConfigDict(env_file=".env", extra="allow")

@lru_cache()
def get_settings() -> Settings:
    return Settings()

