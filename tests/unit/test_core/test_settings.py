import pytest
from pydantic import ValidationError

from app.core.settings import Settings, get_settings


def test_settings_defaults_and_env():
    """Verify settings properties and helper methods."""
    settings = get_settings()
    assert settings.APP_NAME == "Formdata"
    assert settings.DATABASE_URL is not None
    assert settings.JWT_SECRET_KEY is not None
    assert settings.DB_POOL_SIZE >= 1


def test_settings_is_production():
    """Verify is_production property behavior."""
    dev_settings = Settings(ENV="development", DATABASE_URL="sqlite+aiosqlite:///:memory:", JWT_SECRET_KEY="test")
    assert dev_settings.is_production is False
    assert dev_settings.is_development is True

    prod_settings = Settings(ENV="production", DATABASE_URL="postgresql+asyncpg://localhost/db", JWT_SECRET_KEY="test")
    assert prod_settings.is_production is True
    assert prod_settings.is_development is False
