import pytest
from app.core.settings import Settings, settings


def test_settings_loaded():
    """Verify settings properties and loaded values."""
    assert settings.ENV == "development"
    assert settings.DATABASE_URL is not None
    assert settings.JWT_ALGO == "HS256"
    assert settings.ACCESS_TTL_MIN == 15
    assert settings.SECURE_COOKIES is False


def test_settings_properties():
    """Verify access and refresh timedelta computed properties."""
    assert settings.ACCESS_TTL.total_seconds() == 15 * 60
    assert settings.REFRESH_TTL.total_seconds() == 10080 * 60

