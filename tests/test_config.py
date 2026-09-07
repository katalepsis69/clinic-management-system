from app.config import get_settings

def test_settings_load_defaults():
    settings = get_settings()
    assert settings.APP_NAME == "Clinic Management System"
    assert settings.DATABASE_URL.startswith("sqlite")
    assert settings.DEMO_MODE is True
