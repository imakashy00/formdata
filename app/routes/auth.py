from fastapi import APIRouter, Depends, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession
from loguru import logger as log

from app.schemas.error import AuthenticationError, TokenGenerationError
from app.services.auth import AuthService
from app.services.dependencies import (
    _exchange_google_token,
    _issue_and_store_tokens,
    _validate_userinfo,
)
from app.services.cookies import clear_auth_cookies, set_auth_cookies
from app.services.blacklist import revoke
from app.schemas.user import RegisterUser
from app.crud.user import register_user
from app.services.oauth import oauth
from app.core.db import get_db


router = APIRouter(tags=["auth"])


@router.post("/auth")
async def login(request: Request):
    redirect_uri = request.url_for("auth_callback")
    return await oauth.google.authorize_redirect(request, redirect_uri)  # type: ignore


@router.get("/auth/callback")
async def auth_callback(request: Request, db: AsyncSession = Depends(get_db)):
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

        # and registration (if user is new) and return the internal user_id.
        user_id = await register_user(userinfo=user_info_schema, db=db)
        log.info(f"👤 User registration/lookup successful. Internal ID: {user_id}")

    except Exception as e:
        # Catch specific DB exceptions (e.g., integrity errors) if possible
        log.critical(
            f"🚫Database Error during user registration/lookup: {e}", exc_info=True
        )
        return RedirectResponse(url="/", status_code=303)
    # 3. Token Issuance and Storage
    try:
        access_token, refresh_token = await _issue_and_store_tokens(
            user_id=user_id, email=user_data["email"]
        )
    except TokenGenerationError:
        return RedirectResponse(url="/", status_code=303)

    # 4. Final Response and Cookie Setting
    resp = RedirectResponse(url="/", status_code=303)
    log.debug("Setting secure authentication cookies.")
    set_auth_cookies(resp, access_token, refresh_token)

    return resp


@router.post("/logout")
async def logout(request: Request):
    resp = RedirectResponse(url="/", status_code=303)  # 303 = See Other
    # best-effort: try revoke access + refresh if present
    for name in ("access_token", "refresh_token"):
        token = request.cookies.get(name)
        if not token:
            continue
        try:
            payload = AuthService.decode(token)
        except Exception:
            continue
        is_refresh = payload.get("type") == "refresh"
        await revoke(
            payload["jti"], payload["exp"], delete_refresh_whitelist=is_refresh
        )
    clear_auth_cookies(resp)
    return resp
