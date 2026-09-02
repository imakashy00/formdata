import uuid
from datetime import UTC, datetime, timedelta
import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import BLACKLIST, WHITELIST, AuthToken
from app.services.blacklist import is_revoked, is_whitelisted


@pytest.mark.asyncio
async def test_is_revoked_false_when_empty(db_session: AsyncSession):
    """Verify is_revoked returns False for tokens not marked revoked."""
    revoked = await is_revoked(db_session, jti="random_jti_123")
    assert revoked is False


@pytest.mark.asyncio
async def test_is_revoked_true_when_blacklisted(db_session: AsyncSession):
    """Verify is_revoked returns True for active blacklisted tokens."""
    token = AuthToken(
        jti="revoked_jti_789",
        token_type=BLACKLIST,
        user_id=uuid.uuid4(),
        expires_at=datetime.now(UTC) + timedelta(hours=1),
    )
    db_session.add(token)
    await db_session.commit()

    revoked = await is_revoked(db_session, jti="revoked_jti_789")
    assert revoked is True


@pytest.mark.asyncio
async def test_is_whitelisted(db_session: AsyncSession):
    """Verify is_whitelisted returns True for valid active whitelisted refresh tokens."""
    token = AuthToken(
        jti="whitelist_jti_111",
        token_type=WHITELIST,
        user_id=uuid.uuid4(),
        expires_at=datetime.now(UTC) + timedelta(days=3),
    )
    db_session.add(token)
    await db_session.commit()

    whitelisted = await is_whitelisted(db_session, jti="whitelist_jti_111")
    assert whitelisted is True
