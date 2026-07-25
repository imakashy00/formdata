from typing import Annotated

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from loguru import logger as log
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.core.settings import settings
from app.models.user import Form as FormDB
from app.models.user import Submission, User
from app.routes.page import get_current_user
from app.services.form import (
    _build_form_context,
    check_honeypot,
    check_rate_limit,
    check_user_agent,
    content_score,
    get_form_temp,
    route,
    verify_bot_check,
    verify_session,
)

client_form_router = APIRouter(prefix="/f")


@client_form_router.post("/{form_id}")
async def handle_form_submit(
    form_id: str,
    request: Request,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    query = select(FormDB).where(FormDB.public_id == form_id)
    result = await db.execute(query)
    form = result.scalar_one_or_none()

    if not form:
        form = get_form_temp(form_id)

    if not form:
        return JSONResponse({"error": "unknown form"}, status_code=404)

    form_context = _build_form_context(form)

    # --- edge-equivalent: rate limiting ---
    ip = request.client.host if request.client else "unknown"
    if not await check_rate_limit("ip", ip, *settings.RATE_LIMIT_IP):
        return JSONResponse({"error": "rate limit exceeded"}, status_code=429)
    if not await check_rate_limit("form", form_id, *settings.RATE_LIMIT_FORM):
        return JSONResponse(
            {"error": "form is receiving too many submissions"}, status_code=429
        )

    # --- fast structural checks ---
    if not check_user_agent(request):
        return JSONResponse({"error": "missing user agent"}, status_code=400)

    form_data = dict(await request.form())

    if not check_honeypot(form_data, form_context["honeypot"]):
        # Bots that fill every field trip this. Respond as if successful —
        # no need to teach the bot what tripped it.
        return JSONResponse({"status": "accepted"}, status_code=200)

    missing = form_context["required"] - form_data.keys()
    if missing:
        return JSONResponse(
            {"error": f"missing fields: {sorted(missing)}"}, status_code=400
        )
    token_value = form_data.get("sessionToken")
    if token_value:
        session_ok, session_err = await verify_session(str(token_value), form_id)
        if not session_ok:
            return JSONResponse({"error": session_err}, status_code=400)

    # --- bot verification (ALTCHA by default, or the customer's Turnstile) ---
    bot_secret = (
        form_context["turnstile_secret"]
        if form_context["bot_provider"] == "cloudflare_turnstile"
        else None
    )
    bot_ok, bot_err = await verify_bot_check(
        form_context, form_data, request, bot_secret
    )
    if not bot_ok:
        return JSONResponse({"error": f"bot check failed: {bot_err}"}, status_code=400)

    submission_payload = {
        key: value
        for key, value in form_data.items()
        if key not in {"sessionToken", "altcha", "cf-turnstile-response"}
    }

    db_form: FormDB | None = None
    if not isinstance(form, dict):
        db_form = form

    if db_form is not None:
        try:
            submission = Submission(form_id=db_form.id, payload=submission_payload)
            db.add(submission)
            await db.commit()
        except SQLAlchemyError as exc:
            await db.rollback()
            log.exception(f"Failed to persist submission for form {form_id}: {exc}")
            return JSONResponse({"error": "failed to save submission"}, status_code=500)

    # --- content filter (scored, not hard-reject) ---
    score, reasons = await content_score(form_id, form_context, form_data)
    decision = route(score)

    if decision == "reject":
        return JSONResponse({"status": "rejected", "reasons": reasons}, status_code=200)

    return JSONResponse({"status": decision}, status_code=200)


# users might upload sensitive private files like legal documents or resumes.
# Do not toggle your R2 bucket to "Public".
# Instead, keep it entirely private and
# use your Cloudflare Worker to generate
# S3-compatible Presigned URLs with short expiration windows
# (e.g., valid for 15 minutes).
# When a logged-in SaaS customer checks their dashboard,
# they will click the link, your backend will authenticate them, and
# securely serve the file.
# Because this is a Formspree alternative, ``
