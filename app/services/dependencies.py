from typing import Annotated
from uuid import UUID

from fastapi import Depends, HTTPException, Request
from loguru import logger as log
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.db import get_db
from app.core.settings import settings
from app.models.user import Project, User
from app.schemas.error import AuthenticationError, TokenGenerationError
from app.services import blacklist
from app.services.auth import decode
from app.services.jwt import create_token
from app.services.oauth import get_oauth_redirect_uri, oauth


async def _exchange_google_token(request: Request) -> dict:
    """Exchange an OAuth callback only after Authlib validates its state."""
    try:
        token = await oauth.google.authorize_access_token(request)  # type: ignore
        if token and token.get("access_token"):
            return token
    except Exception as e:
        log.warning(f"OAuth callback rejected: {e}")

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


async def _issue_and_store_tokens(
    db: AsyncSession, user_id: UUID, email: str
) -> tuple[str, str]:
    """Generates and whitelists access and refresh tokens."""
    try:
        # 1. Issue JWTs
        access, _, _ = create_token(
            sub=str(user_id), email=email, type="access", ttl=settings.ACCESS_TTL
        )
        refresh, refresh_jti, refresh_exp = create_token(
            sub=str(user_id), email=email, type="refresh", ttl=settings.REFRESH_TTL
        )

        log.info(f"🔑 Tokens issued for user_id: {user_id}. Refresh JTI: {refresh_jti}")

        await blacklist.whitelist_refresh(
            db, jti=refresh_jti, user_id=user_id, email=email, exp_unix=refresh_exp
        )

        return access, refresh

    except Exception as e:
        log.error(
            f"🚫Error while issuing or storing tokens for user {user_id}: {e}",
            exc_info=True,
        )
        raise TokenGenerationError("Failed to issue security tokens.")


async def refresh_tokens(db: AsyncSession, refresh_token: str):
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
        payload = decode(refresh_token)
    except Exception:
        raise HTTPException(401, "Invalid or expired refresh token")

    jti = payload["jti"]

    # Verify token type
    if payload.get("type") != "refresh":
        raise HTTPException(401, "Wrong token type")

    # Check if token is revoked (blacklist)
    if await blacklist.is_revoked(db, jti):
        raise HTTPException(401, "Refresh token revoked")

    # Check if token exists in whitelist
    if not await blacklist.is_whitelisted(db, jti):
        raise HTTPException(401, "Refresh token expired or not found")

    # Extract user info for new tokens
    user_id = payload["sub"]
    email = payload["email"]

    # ROTATE refresh: delete old and add new
    await blacklist.remove_whitelist(db, jti)

    # Issue new tokens
    new_access, _, _ = create_token(
        sub=user_id, email=email, type="access", ttl=settings.ACCESS_TTL
    )
    new_refresh, new_rjti, new_rexp = create_token(
        sub=user_id, email=email, type="refresh", ttl=settings.REFRESH_TTL
    )

    # Store new refresh token in whitelist
    await blacklist.whitelist_refresh(
        db, jti=new_rjti, user_id=user_id, email=email, exp_unix=new_rexp
    )

    return new_access, new_refresh


async def current_user(
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """
    Extract user from request.state (already JWT-validated)
    and load DB record.
    """
    payload = getattr(request.state, "user", None)
    if not payload:
        return None

    user_id = payload.get("sub")
    # ✅ Fix: Use async select with eager loading
    result = await db.execute(
        select(User).options(selectinload(User.subscription)).filter(User.id == user_id)
    )
    user = result.scalars().first()

    if not user:
        raise HTTPException(status_code=401, detail="User not found")

    return user


async def require_owned_project(
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User | None, Depends(current_user)],
    project_id: str | None = None,
) -> None:
    """Require ownership for routes that include a project path parameter."""
    if project_id is None:
        return
    if user is None:
        raise HTTPException(status_code=401, detail="Authentication required")
    try:
        project_uuid = UUID(project_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail="Project not found") from exc
    project = await db.scalar(
        select(Project.id).where(Project.id == project_uuid, Project.user_id == user.id)
    )
    if project is None:
        # Deliberately use 404 so project identifiers are not an oracle.
        raise HTTPException(status_code=404, detail="Project not found")
