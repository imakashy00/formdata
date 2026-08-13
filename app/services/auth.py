# app/services/auth.py

import jwt
from fastapi import HTTPException
from jwt.exceptions import ExpiredSignatureError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.settings import settings
from app.services.blacklist import is_revoked


def decode(token: str) -> dict:
    try:
        return jwt.decode(
            token,
            str(settings.JWT_SECRET),
            algorithms=[settings.JWT_ALGO],
            options={"require": ["exp", "jti", "sub", "type"]},
        )
    except ExpiredSignatureError:
        # Re-raise so middleware can handle expired tokens appropriately
        raise
    except Exception:
        raise HTTPException(status_code=401, detail="invalid_token")


async def validate_access(payload, db: AsyncSession):
    if await is_revoked(db, payload["jti"]):
        raise HTTPException(status_code=401, detail="revoked")

    return payload


async def try_refresh(db: AsyncSession, refresh_token: str):
    """
    Try refreshing tokens. If it fails, raise an HTTPException(401).
    """
    from app.services.dependencies import (
        refresh_tokens,
    )  # lazy import avoids circular

    try:
        new_access, new_refresh = await refresh_tokens(db, refresh_token)
        return new_access, new_refresh
    except ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="refresh_expired")
    except Exception:
        raise HTTPException(status_code=401, detail="refresh_failed")
