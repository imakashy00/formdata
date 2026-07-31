from datetime import UTC, datetime

from app.core.db import get_db
from app.core.settings import settings
from app.models.user import User
from app.schemas.error import AuthenticationError, TokenGenerationError
from app.services.auth import AuthService
from app.services.blacklist import is_revoked, redis_client
from app.services.jwt import create_token
from app.services.oauth import oauth
from fastapi import Depends, HTTPException, Request
from loguru import logger as log
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload


async def _exchange_google_token(request: Request) -> dict:
    """Handles the token exchange with Google OAuth."""
    try:
        # Use an appropriate timeout if the oauth client supports it
        token = await oauth.google.authorize_access_token(request)  # type: ignore
        return token
    except Exception as e:
        # Catch specific exceptions from the OAuth client if possible
        # e.g., Authlib's OAuthError for better granularity
        log.error(f"🚫OAuth Error during token exchange: {e}", exc_info=True)
        # Re-raise a custom exception for the main function to handle redirection
        raise AuthenticationError("Failed to get token from Google.")


def _validate_userinfo(token: dict) -> dict:
    """Extracts and validates essential user information."""
    userinfo = token.get("userinfo") or {}

    # Use explicit variable names for clarity
    user_email = userinfo.get("email")
    google_sub_id = userinfo.get("sub")

    if not user_email or not google_sub_id:
        log.error("Essential user info (email or sub) missing in Google response.")
        raise AuthenticationError("Incomplete user information received.")

    return {
        "name": userinfo.get("name") or "",
        "email": user_email,
        "google_sub": google_sub_id,
        # Default to None/empty string if not present, but better to use a default for picture
        "picture": userinfo.get("picture") or "",
    }


async def _issue_and_store_tokens(user_id: str, email: str) -> tuple[str, str]:
    """Generates and whitelists access and refresh tokens."""
    try:
        # 1. Issue JWTs
        access, _, _ = create_token(
            sub=user_id, email=email, type="access", ttl=settings.ACCESS_TTL
        )
        refresh, refresh_jti, refresh_exp = create_token(
            sub=user_id, email=email, type="refresh", ttl=settings.REFRESH_TTL
        )

        log.info(f"🔑 Tokens issued for user_id: {user_id}. Refresh JTI: {refresh_jti}")

        # 2. Store refresh token JTI in Redis (Whitelist)
        now_ts = int(datetime.now(UTC).timestamp())
        redis_ttl = refresh_exp - now_ts

        # Security Note: Use a more specific key namespace for clarity and isolation
        await redis_client.setex(
            f"auth:refresh_jti:{refresh_jti}",
            redis_ttl,
            "1",  # Value '1' is arbitrary, just indicates presence
        )

        return access, refresh

    except Exception as e:
        log.error(
            f"🚫Error while issuing or storing tokens for user {user_id}: {e}",
            exc_info=True,
        )
        raise TokenGenerationError("Failed to issue security tokens.")


async def refresh_tokens(refresh_token: str):
    """
    Validate refresh token and issue new access + refresh tokens.
    Flow:
    1. Decode and validate token signature/expiry
    2. Verify token type is "refresh"
    3. Check blacklist (revoked tokens)
    4. Check whitelist (token still valid in Redis)
    5. Rotate tokens (delete old, create new)
    """
    try:
        payload = AuthService.decode(refresh_token)
    except Exception:
        raise HTTPException(401, "Invalid or expired refresh token")

    jti = payload["jti"]
    
    # Verify token type
    if payload.get("type") != "refresh":
        raise HTTPException(401, "Wrong token type")
    
    # Check if token is revoked (blacklist)
    if await is_revoked(jti):
        raise HTTPException(401, "Refresh token revoked")
    
    # Check if token exists in whitelist
    exists = await redis_client.exists(f"auth:refresh_jti:{jti}")
    if not exists:
        raise HTTPException(401, "Refresh token expired or not found")
    
    # Extract user info for new tokens
    user_id = payload["sub"]
    email = payload["email"]

    # ROTATE refresh: delete old and add new
    await redis_client.delete(f"auth:refresh_jti:{jti}")

    # Issue new tokens
    new_access, _, _ = create_token(
        sub=user_id, email=email, type="access", ttl=settings.ACCESS_TTL
    )
    new_refresh, new_rjti, new_rexp = create_token(
        sub=user_id, email=email, type="refresh", ttl=settings.REFRESH_TTL
    )
    
    # Store new refresh token in whitelist
    await redis_client.setex(
        f"auth:refresh_jti:{new_rjti}",
        new_rexp - int(datetime.now(UTC).timestamp()),
        "1",
    )

    return new_access, new_refresh


async def current_user(
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """
    Extract user from request.state (already JWT-validated)
    and load DB record.
    """
    payload = getattr(request.state, "user", None)
    if not payload:
        raise HTTPException(status_code=401, detail="Unauthorized")

    user_id = payload.get("sub")
    # ✅ Fix: Use async select with eager loading
    result = await db.execute(
        select(User).options(selectinload(User.subscription)).filter(User.id == user_id)
    )
    user = result.scalars().first()

    if not user:
        raise HTTPException(status_code=401, detail="User not found")

    return user

