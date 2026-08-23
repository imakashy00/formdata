from datetime import UTC, datetime
from typing import cast
from uuid import UUID

from sqlalchemy import CursorResult, delete, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import BLACKLIST, WHITELIST, AuthToken


async def is_revoked(db: AsyncSession, jti: str) -> bool:
    stmt = select(AuthToken.jti).where(
        AuthToken.jti == jti,
        AuthToken.token_type == BLACKLIST,
        AuthToken.expires_at > datetime.now(UTC),
    )
    return (await db.execute(stmt)).scalar_one_or_none() is not None


async def revoke(
    db: AsyncSession,
    jti: str,
    exp_unix: int,
    user_id: UUID,
    email: str | None = None,
    delete_refresh_whitelist: bool = False,
) -> None:
    """Mark `jti` as revoked. If it was previously whitelisted (an active
    refresh token), this upsert flips that same row to blacklisted —
    is_whitelisted() now says no, is_revoked() now says yes."""
    expires_at = datetime.fromtimestamp(exp_unix, tz=UTC)
    stmt = (
        pg_insert(AuthToken)
        .values(
            jti=jti,
            user_id=user_id,
            token_type=BLACKLIST,
            email=email,
            expires_at=expires_at,
        )
        .on_conflict_do_update(
            index_elements=[AuthToken.jti],
            set_={"token_type": BLACKLIST, "expires_at": expires_at},
        )
    )
    await db.execute(stmt)
    if delete_refresh_whitelist:
        await db.execute(
            delete(AuthToken).where(
                AuthToken.jti == jti, AuthToken.token_type == WHITELIST
            )
        )
    await db.commit()


async def whitelist_refresh(
    db: AsyncSession, jti: str, user_id: UUID, email: str, exp_unix: int
) -> None:
    expires_at = datetime.fromtimestamp(exp_unix, tz=UTC)
    stmt = (
        pg_insert(AuthToken)
        .values(
            jti=jti,
            user_id=user_id,
            token_type=WHITELIST,
            email=email,
            expires_at=expires_at,
        )
        .on_conflict_do_update(
            index_elements=[AuthToken.jti],
            set_={"token_type": WHITELIST, "expires_at": expires_at, "email": email},
        )
    )
    await db.execute(stmt)
    await db.commit()


async def is_whitelisted(db: AsyncSession, jti: str) -> bool:
    stmt = select(AuthToken.jti).where(
        AuthToken.jti == jti,
        AuthToken.token_type == WHITELIST,
        AuthToken.expires_at > datetime.now(UTC),
    )
    return (await db.execute(stmt)).scalar_one_or_none() is not None


async def remove_whitelist(db: AsyncSession, jti: str) -> None:
    await db.execute(
        delete(AuthToken).where(AuthToken.jti == jti, AuthToken.token_type == WHITELIST)
    )
    await db.commit()


async def cleanup_expired(db: AsyncSession) -> int:
    result = await db.execute(
        delete(AuthToken).where(AuthToken.expires_at <= datetime.now(UTC))
    )
    await db.commit()
    return cast(CursorResult, result).rowcount or 0
