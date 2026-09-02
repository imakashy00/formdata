from datetime import timedelta
import pytest
import jwt

from app.core.settings import settings
from app.services.jwt import create_token


def test_create_access_token():
    """Verify create_token generates a signed JWT with expected claims."""
    token, jti, exp = create_token(
        sub="usr_12345",
        email="test@example.com",
        type="access",
        ttl=timedelta(minutes=15),
    )
    assert token is not None
    assert jti is not None
    assert exp > 0

    decoded = jwt.decode(token, str(settings.JWT_SECRET), algorithms=[settings.JWT_ALGO])
    assert decoded["sub"] == "usr_12345"
    assert decoded["email"] == "test@example.com"
    assert decoded["type"] == "access"
    assert decoded["jti"] == jti


def test_create_refresh_token():
    """Verify create_token generates refresh token with correct type."""
    token, jti, exp = create_token(
        sub="usr_12345",
        email="test@example.com",
        type="refresh",
        ttl=timedelta(days=7),
    )
    decoded = jwt.decode(token, str(settings.JWT_SECRET), algorithms=[settings.JWT_ALGO])
    assert decoded["type"] == "refresh"
