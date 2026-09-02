from datetime import timedelta
import pytest
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.auth import decode, try_refresh, validate_access
from app.services.jwt import create_token


def test_decode_valid_token():
    """Verify decode decodes valid JWT token."""
    token, jti, exp = create_token(
        sub="usr_999",
        email="user@test.com",
        type="access",
        ttl=timedelta(minutes=30),
    )
    payload = decode(token)
    assert payload["sub"] == "usr_999"
    assert payload["email"] == "user@test.com"


def test_decode_invalid_token_raises_http_401():
    """Verify decode raises HTTPException 401 for corrupted tokens."""
    with pytest.raises(HTTPException) as exc_info:
        decode("corrupted.jwt.token")
    assert exc_info.value.status_code == 401
    assert exc_info.value.detail == "invalid_token"


@pytest.mark.asyncio
async def test_validate_access_unrevoked(db_session: AsyncSession):
    """Verify validate_access returns payload for unrevoked tokens."""
    token, jti, exp = create_token(
        sub="usr_999",
        email="user@test.com",
        type="access",
        ttl=timedelta(minutes=30),
    )
    payload = decode(token)
    validated = await validate_access(payload, db_session)
    assert validated["sub"] == "usr_999"
