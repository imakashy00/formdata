import uuid
import pytest
from fastapi import HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User
from app.schemas.error import AuthenticationError
from app.services.dependencies import _validate_userinfo, current_user


def test_validate_userinfo_valid():
    """Verify _validate_userinfo parses Google OAuth userinfo."""
    token = {
        "userinfo": {
            "name": "Eve Adams",
            "email": "eve@example.com",
            "sub": "google-sub-777",
            "picture": "https://example.com/avatar.jpg",
        }
    }
    extracted = _validate_userinfo(token)
    assert extracted["name"] == "Eve Adams"
    assert extracted["email"] == "eve@example.com"
    assert extracted["google_sub"] == "google-sub-777"


def test_validate_userinfo_missing_fields_raises_error():
    """Verify _validate_userinfo raises AuthenticationError when email or sub is missing."""
    with pytest.raises(AuthenticationError):
        _validate_userinfo({"userinfo": {}})


@pytest.mark.asyncio
async def test_current_user_none_when_unauthenticated(db_session: AsyncSession):
    """Verify current_user returns None if no user state is in request."""
    scope = {"type": "http", "state": {}}
    request = Request(scope)
    user = await current_user(request=request, db=db_session)
    assert user is None


@pytest.mark.asyncio
async def test_current_user_found(db_session: AsyncSession, sample_user: User):
    """Verify current_user loads User model when sub matches."""
    scope = {"type": "http", "state": {"user": {"sub": sample_user.id, "email": sample_user.email}}}
    request = Request(scope)
    user = await current_user(request=request, db=db_session)
    assert user is not None
    assert user.id == sample_user.id
