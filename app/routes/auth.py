from typing import Annotated

from fastapi import APIRouter, Depends, Request
from fastapi.responses import RedirectResponse
from loguru import logger as log
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.models.user import Integration, IntegrationProvider, User
from app.schemas.error import AuthenticationError, TokenGenerationError
from app.schemas.user import RegisterUser
from app.services.auth import decode
from app.services.blacklist import revoke
from app.services.cookies import clear_auth_cookies, set_auth_cookies
from app.services.crud.user import register_user
from app.services.dependencies import (
    _exchange_google_token,
    _issue_and_store_tokens,
    _validate_userinfo,
    current_user,
)
from app.services.oauth import oauth

auth_router = APIRouter(tags=["auth"])


@auth_router.post("/auth")
async def login(request: Request):
    redirect_uri = request.url_for("auth_callback")
    return await oauth.google.authorize_redirect(request, redirect_uri)


@auth_router.get("/auth/callback")
async def auth_callback(request: Request, db: Annotated[AsyncSession, Depends(get_db)]):
    # 1. Token Exchange and User Info Validation
    try:
        token = await _exchange_google_token(request)
        user_data = _validate_userinfo(token)
    except AuthenticationError:
        return RedirectResponse(url="/", status_code=303)

    # 2. User Registration or Login (CRUD Operation)
    user_id = None
    try:
        # Map validated data to the registration schema
        user_info_schema = RegisterUser(**user_data)
        # if user_info_schema.email != "yakashadav26@gmail.com":
        #     return RedirectResponse(url="/", status_code=303)
        # and registration (if user is new) and return the internal user_id.
        user_id = await register_user(userinfo=user_info_schema, db=db)
        log.info(f"👤 User registration/lookup successful. Internal ID: {user_id}")

        # Store or update Google OAuth write token in Integration table for Google Sheets
        google_access_token = token.get("access_token")
        google_refresh_token = token.get("refresh_token")
        if google_access_token and user_id:
            try:
                result = await db.execute(
                    select(Integration).where(
                        Integration.user_id == user_id,
                        Integration.provider == IntegrationProvider.GOOGLE_SHEETS,
                    )
                )
                user_integration = result.scalar_one_or_none()
                if not user_integration:
                    user_integration = Integration(
                        user_id=user_id,
                        provider=IntegrationProvider.GOOGLE_SHEETS,
                        access_token=google_access_token,
                        refresh_token=google_refresh_token,
                        enabled=True,
                    )
                    db.add(user_integration)
                else:
                    user_integration.access_token = google_access_token
                    if google_refresh_token:
                        user_integration.refresh_token = google_refresh_token
                await db.commit()
            except Exception as integ_err:
                log.warning(f"Could not persist Google OAuth write token: {integ_err}")

    except SQLAlchemyError as e:
        # Catch specific DB exceptions (e.g., integrity errors) if possible
        log.critical(
            f"🚫Database Error during user registration/lookup: {e}", exc_info=True
        )
        return RedirectResponse(url="/", status_code=303)
    # 3. Token Issuance and Storage
    try:
        access_token, refresh_token = await _issue_and_store_tokens(
            db, user_id=user_id, email=user_data["email"]
        )
    except TokenGenerationError:
        return RedirectResponse(url="/", status_code=303)

    # 4. Final Response and Cookie Setting
    resp = RedirectResponse(url="/", status_code=303)
    log.debug("Setting secure authentication cookies.")
    set_auth_cookies(resp, access_token, refresh_token)

    return resp


@auth_router.post("/logout")
async def logout(
    request: Request,
    user: Annotated[User, Depends(current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    resp = RedirectResponse(url="/", status_code=303)  # 303 = See Other
    # best-effort: try revoke access + refresh if present
    for name in ("access_token", "refresh_token"):
        token = request.cookies.get(name)
        if not token:
            continue
        try:
            payload = decode(token)
        except SQLAlchemyError:
            continue
        is_refresh = payload.get("type") == "refresh"
        await revoke(
            db,
            payload["jti"],
            payload["exp"],
            user.id,
            user.email,
            delete_refresh_whitelist=is_refresh,
        )
    clear_auth_cookies(resp)
    return resp
