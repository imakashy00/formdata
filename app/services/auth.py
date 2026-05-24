# app/services/auth.py
from fastapi import HTTPException
import jwt
from jwt.exceptions import ExpiredSignatureError
from app.core.settings import settings
from app.services.blacklist import is_revoked


class AuthService:
    @staticmethod
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

    @staticmethod
    async def validate_access(token: str):
        try:
            payload = AuthService.decode(token)
        except ExpiredSignatureError:
            raise HTTPException(status_code=401, detail="access_expired")

        if payload.get("type") != "access":
            raise HTTPException(status_code=401, detail="wrong_token_type")

        if await is_revoked(payload["jti"]):
            raise HTTPException(status_code=401, detail="revoked")

        return payload

    @staticmethod
    async def try_refresh(refresh_token: str):
        """
        Try refreshing tokens. If it fails, raise an HTTPException(401).
        """
        from app.services.dependencies import (
            refresh_tokens,
        )  # lazy import avoids circular

        try:
            new_access, new_refresh = await refresh_tokens(refresh_token)
            return new_access, new_refresh
        except ExpiredSignatureError:
            raise HTTPException(status_code=401, detail="refresh_expired")
        except Exception:
            raise HTTPException(status_code=401, detail="refresh_failed")
