import base64
import json
from typing import Annotated
from uuid import UUID

import httpx
from fastapi import APIRouter, Depends, Request
from fastapi.responses import RedirectResponse
from loguru import logger as log
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.models.user import Integration, IntegrationProvider, User
from app.repositories.form_repository import FormRepository
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


def _decode_oauth_state(state_str: str | None) -> dict:
    if not state_str:
        return {}
    try:
        padded = state_str + "=" * (-len(state_str) % 4)
        data = json.loads(base64.urlsafe_b64decode(padded.encode()).decode())
        if isinstance(data, dict):
            return data
    except Exception:
        pass
    return {}


async def process_google_sheets_callback(
    request: Request,
    db: AsyncSession,
) -> RedirectResponse:
    state_param = request.query_params.get("state")
    state_data = _decode_oauth_state(state_param)
    if not state_data and "google_sheets_state" in request.session:
        state_data = request.session.pop("google_sheets_state", {})

    token = None
    try:
        token = await oauth.google_sheets.authorize_access_token(request)
    except Exception as exc:
        log.warning(f"Failed authorize_access_token on google_sheets client: {exc}. Trying google client...")
        try:
            token = await oauth.google.authorize_access_token(request)
        except Exception as exc2:
            log.error(f"Failed authorize_access_token on google client: {exc2}")

    project_id = state_data.get("project_id")
    form_id = state_data.get("form_id")
    user_id = state_data.get("user_id")

    if not token or not token.get("access_token"):
        log.error("Failed to retrieve access token from Google OAuth for Google Sheets.")
        fallback_url = (
            f"/projects/{project_id}/forms/{form_id}?tab=integrations&error=auth_failed"
            if (project_id and form_id)
            else "/"
        )
        return RedirectResponse(url=fallback_url, status_code=303)

    access_token = token.get("access_token")
    refresh_token = token.get("refresh_token")

    if not user_id:
        user = await current_user(request, db)
        if user:
            user_id = str(user.id)

    if user_id:
        try:
            u_uuid = UUID(str(user_id))
            integ_res = await db.execute(
                select(Integration).where(
                    Integration.user_id == u_uuid,
                    Integration.provider == IntegrationProvider.GOOGLE_SHEETS,
                )
            )
            user_integ = integ_res.scalar_one_or_none()
            if not user_integ:
                user_integ = Integration(
                    user_id=u_uuid,
                    provider=IntegrationProvider.GOOGLE_SHEETS,
                    access_token=access_token,
                    refresh_token=refresh_token,
                    integration_metadata={"scope": "https://www.googleapis.com/auth/drive.file"},
                    enabled=True,
                )
                db.add(user_integ)
            else:
                user_integ.access_token = access_token
                if refresh_token:
                    user_integ.refresh_token = refresh_token
                user_integ.enabled = True
                user_integ.integration_metadata = {
                    **(user_integ.integration_metadata or {}),
                    "scope": "https://www.googleapis.com/auth/drive.file",
                }
            await db.commit()
        except Exception as exc:
            log.error(f"Failed to persist Google Sheets Integration: {exc}")

    if form_id and project_id:
        form_repo = FormRepository(db)
        form = await form_repo.get_by_id_and_project(form_id, project_id)
        if form:
            current_map = await form_repo.get_integration_map(form_id, project_id)
            gs_cfg = current_map.get("google_sheets", {})
            sheet_url = gs_cfg.get("sheet_url")
            spreadsheet_id = gs_cfg.get("spreadsheet_id")
            worksheet_name = gs_cfg.get("worksheet_name") or "Submissions"

            # If no spreadsheet configured yet, auto-create one in Google Drive under drive.file!
            if not sheet_url or not spreadsheet_id:
                try:
                    async with httpx.AsyncClient(timeout=15.0) as client:
                        create_res = await client.post(
                            "https://sheets.googleapis.com/v4/spreadsheets",
                            headers={"Authorization": f"Bearer {access_token}"},
                            json={
                                "properties": {"title": f"{form.name} Submissions (Formdata)"},
                                "sheets": [{"properties": {"title": worksheet_name}}],
                            },
                        )
                        if create_res.status_code == 200:
                            created_data = create_res.json()
                            spreadsheet_id = created_data.get("spreadsheetId")
                            sheet_url = f"https://docs.google.com/spreadsheets/d/{spreadsheet_id}/edit"
                            # Initialize standard headers
                            await client.post(
                                f"https://sheets.googleapis.com/v4/spreadsheets/{spreadsheet_id}/values/{worksheet_name}!A1:append?valueInputOption=USER_ENTERED",
                                headers={"Authorization": f"Bearer {access_token}"},
                                json={"values": [["Submitted At", "Country"]]},
                            )
                except Exception as exc:
                    log.warning(f"Could not auto-create Google Spreadsheet: {exc}")

            new_config = {
                "sheet_url": sheet_url or "",
                "spreadsheet_id": spreadsheet_id or "",
                "worksheet_name": worksheet_name,
                "access_token": access_token,
            }
            if refresh_token:
                new_config["refresh_token"] = refresh_token

            await form_repo.upsert_form_integration(
                form_id,
                project_id,
                IntegrationProvider.GOOGLE_SHEETS,
                new_config,
                enabled=True,
            )
            await db.commit()

        return RedirectResponse(
            url=f"/projects/{project_id}/forms/{form_id}?tab=integrations&connected=google_sheets",
            status_code=303,
        )

    return RedirectResponse(url="/projects", status_code=303)


@auth_router.get("/auth/google_sheets/callback", name="google_sheets_callback")
async def google_sheets_callback(
    request: Request, db: Annotated[AsyncSession, Depends(get_db)]
):
    return await process_google_sheets_callback(request, db)


@auth_router.post("/auth")
async def login(request: Request):
    redirect_uri = request.url_for("auth_callback")
    return await oauth.google.authorize_redirect(request, redirect_uri)


@auth_router.get("/auth/callback")
async def auth_callback(request: Request, db: Annotated[AsyncSession, Depends(get_db)]):
    # Check if this callback was for Google Sheets integration
    state_param = request.query_params.get("state")
    state_data = _decode_oauth_state(state_param)
    if state_data.get("type") == "google_sheets" or "google_sheets_state" in request.session:
        return await process_google_sheets_callback(request, db)

    # 1. Token Exchange and User Info Validation
    try:
        token = await _exchange_google_token(request)
        user_data = _validate_userinfo(token)
    except AuthenticationError:
        return RedirectResponse(url="/", status_code=303)

    # 2. User Registration or Login (CRUD Operation)
    user_id = None
    try:
        user_info_schema = RegisterUser(**user_data)
        user_id = await register_user(userinfo=user_info_schema, db=db)
        log.info(f"👤 User registration/lookup successful. Internal ID: {user_id}")
    except SQLAlchemyError as e:
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
