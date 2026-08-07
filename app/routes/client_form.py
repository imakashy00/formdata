from typing import Annotated
from urllib.parse import urlparse

import pycountry
from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    HTTPException,
    Request,
    Response,
    status,
)
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from loguru import logger as log
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.core.settings import settings
from app.models.user import Form as FormDB
from app.models.user import Project, Submission, SubmissionStatus, User
from app.services.email_service import EmailService
from app.services.form import (
    check_honeypot,
    check_rate_limit,
    check_user_agent,
    verify_bot_check,
)

_RESERVED_FIELD_NAMES = {"cf-turnstile-response", "_next"}

client_form_router = APIRouter(prefix="/f")


def _client_ip(request: Request) -> str:
    """Best-effort real visitor IP.

    Behind Cloudflare, request.client.host is the edge/proxy IP, not the
    visitor's — every submission would look like it comes from the same
    address, which silently breaks per-IP rate limiting. Cloudflare sets
    CF-Connecting-IP on every request it proxies; fall back to
    X-Forwarded-For, then to the raw socket peer for local/dev use.
    """
    cf_ip = request.headers.get("cf-connecting-ip")
    if cf_ip:
        return cf_ip
    xff = request.headers.get("x-forwarded-for")
    if xff:
        return xff.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def _flatten_form_data(raw_form) -> dict:
    """Convert Starlette's multi-dict FormData into a plain dict without
    silently dropping repeated keys (checkboxes, multi-selects).

    dict(await request.form()) keeps only the *last* value for any field
    name Submitted more than once — this fixes that.
    """
    flat: dict[str, str | list] = {}
    for key in raw_form:
        values = raw_form.getlist(key)
        # Only flatten plain string fields; file uploads are handled
        # separately by the caller and shouldn't collapse into this dict.
        values = [v for v in values]
        flat[key] = values[0] if len(values) == 1 else values
    return flat


def _resolve_redirect_target(
    form_data: dict, request: Request, form: FormDB
) -> str | None:
    """Where to send the visitor's browser after a plain (non-AJAX) form
    POST. Mirrors Formspree's `_next` convention, but refuses to redirect
    to an attacker-controlled absolute URL (open-redirect guard).
    """
    next_url = form_data.get("_next")
    referer = request.headers.get("referer")

    if next_url:
        parsed = urlparse(str(next_url))
        if not parsed.netloc:
            return str(next_url)  # relative path — always safe

        allowed_host = form.allowed_domains
        referer_host = urlparse(referer).netloc if referer else None
        if parsed.netloc in {allowed_host[0], referer_host}:
            return str(next_url)

        log.warning(f"Ignoring untrusted _next redirect target: {next_url!r}")

    return referer


def _finish(
    request: Request,
    form_data: dict,
    form: FormDB,
    *,
    json_body: dict,
    status_code: int,
    redirect_ok: bool,
) -> Response:
    """Content-negotiated response.

    JS/fetch integrations send `Accept: application/json` and get JSON back
    (this is the documented Formspree convention). Plain <form> posts get a
    303 redirect back to the customer's page so the visitor doesn't land on
    a raw JSON blob — only used for the "looks successful" paths; real
    validation errors always return JSON so they're visible while a
    developer is wiring up their form.
    """
    wants_json = "application/json" in request.headers.get("accept", "")
    if not wants_json and redirect_ok:
        target = _resolve_redirect_target(form_data, request, form)
        if target:
            fragment = (
                "formdata-success"
                if json_body.get("status") != "error"
                else "formdata-error"
            )
            return RedirectResponse(url=f"{target}#{fragment}", status_code=303)
    return JSONResponse(json_body, status_code=status_code)


@client_form_router.post("/{form_id}")
async def handle_form_submit(
    form_id: str,
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
    background_task: BackgroundTasks,
):

    query = select(FormDB).where(FormDB.public_id == form_id)
    result = await db.execute(query)
    form = result.scalar_one_or_none()

    if not form:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Form Not found"
        )

    if not form:
        return JSONResponse({"error": "unknown form"}, status_code=404)

    # --- edge-equivalent: rate limiting ---
    ip = _client_ip(request)
    if not await check_rate_limit("ip", ip, *settings.RATE_LIMIT_IP):
        return JSONResponse({"error": "rate limit exceeded"}, status_code=429)
    if not await check_rate_limit("form", form_id, *settings.RATE_LIMIT_FORM):
        return JSONResponse(
            {"error": "form is receiving too many submissions"}, status_code=429
        )

    # --- fast structural checks ---
    if not check_user_agent(request):
        return JSONResponse({"error": "missing user agent"}, status_code=400)

    content_type = request.headers.get("content-type", "")
    if content_type.startswith("application/json"):
        # fetch()-based integrations (React, Vue, custom JS) typically send
        # JSON rather than form-encoded data. No multi-value collapsing
        # issue here since a JSON body isn't a multi-dict — a repeated
        # "field" would just be a JSON array, which the caller controls.
        try:
            json_body = await request.json()
        except ValueError:
            return JSONResponse({"error": "invalid JSON body"}, status_code=400)
        if not isinstance(json_body, dict):
            return JSONResponse(
                {"error": "JSON body must be an object"}, status_code=400
            )
        form_data = dict(json_body)
    else:
        # Native <form> posts (multipart/form-data or
        # x-www-form-urlencoded) — what WordPress/plain-HTML embeds send.
        # File uploads only arrive this way; JSON bodies can't carry files.
        raw_form = await request.form()
        form_data = _flatten_form_data(raw_form)

    honeypot_field = form["honeypot"] if isinstance(form, dict) else form.honeypot

    if not check_honeypot(form_data, honeypot_field):
        # Bots that fill every field trip this. Respond exactly like a
        # normal success — including the redirect — so there's nothing
        # for the bot (or whoever's watching its logs) to learn from.
        return _finish(
            request,
            form_data,
            form,
            json_body={"status": "accepted"},
            status_code=200,
            redirect_ok=True,
        )
    required_fields = form_data["required"] if isinstance(form, dict) else {}
    missing = required_fields - form_data.keys()
    if missing:
        return JSONResponse(
            {"error": f"missing fields: {sorted(missing)}"}, status_code=400
        )

    # --- bot verification: honeypot above + Cloudflare Turnstile here ---

    bot_ok, bot_err = await verify_bot_check(form_data, request, form.turnstile_secret)
    if not bot_ok:
        # 1. Clean the payload just like a successful submission
        submission_payload = {
            key: value
            for key, value in form_data.items()
            if key not in _RESERVED_FIELD_NAMES and key != form.honeypot
        }
        # --- Parse Country Location Metadata via pycountry ---
        raw_country_code = request.headers.get("cf-ipcountry")
        country_name = None
        if raw_country_code:
            try:
                country_obj = pycountry.countries.get(alpha_2=raw_country_code.upper())
                if country_obj:
                    country_name = country_obj.name
                else:
                    country_name = raw_country_code
            except ValueError:
                country_name = raw_country_code

        submission_payload = {
            key: value
            for key, value in form_data.items()
            if key not in _RESERVED_FIELD_NAMES and key != form.honeypot
        }
        if country_name:
            submission_payload["country_name"] = country_name

        # 2. Persist the failed verification to the Database as REJECTED
        if form is not None:
            try:
                failed_submission = Submission(
                    form_id=form.id,
                    payload=submission_payload,
                    status=SubmissionStatus.REJECTED,  # Marks it for the spam dashboard review view
                    opened=False,
                    country=country_name,
                )
                db.add(failed_submission)
                await db.commit()
            except SQLAlchemyError as exc:
                await db.rollback()
                log.exception(f"Failed to persist spam row for form {form_id}: {exc}")
                # Don't break the client response flow if internal spam tracking fails

        # 3. Handle client-facing redirect or JSON output loops
        accept_header = request.headers.get("accept", "")
        is_json_request = (
            content_type.startswith("application/json")
            or "application/json" in accept_header
        )

        if is_json_request:
            return JSONResponse(
                status_code=status.HTTP_400_BAD_REQUEST,
                content={"error": "Bot verification failed. Please try again."},
                headers={"HX-Trigger": "turnstile-failed"},
            )

        # Traditional Native <form> action redirect handling fallback
        error_redirect_url = form_data.get("_error_url") or request.headers.get(
            "referer"
        )
        from urllib.parse import parse_qsl, urlparse, urlunparse

        if error_redirect_url:
            # 1. Parse the URL properly
            parsed_url = urlparse(error_redirect_url)

            # 2. Extract and parse only the query string slice safely
            query_params = dict(parse_qsl(parsed_url.query))

            # 3. Inject your error flag parameters
            query_params["error"] = "turnstile_failed"

            # 4. Rebuild the URL using a typed tuple layout
            final_redirect_url = urlunparse(
                (
                    parsed_url.scheme,
                    parsed_url.netloc,
                    parsed_url.path,
                    parsed_url.params,
                    "",
                    parsed_url.fragment,
                )
            )

            return RedirectResponse(
                url=final_redirect_url, status_code=status.HTTP_303_SEE_OTHER
            )

        return HTMLResponse(
            status_code=400,
            content="<h1>Submission Failed</h1><p>Bot verification failed.</p>",
        )

    # --- Parse Country Location Metadata via pycountry ---
    raw_country_code = request.headers.get("cf-ipcountry")
    country_name = None
    if raw_country_code:
        try:
            country_obj = pycountry.countries.get(alpha_2=raw_country_code.upper())
            if country_obj:
                country_name = country_obj.name
            else:
                country_name = raw_country_code
        except ValueError:
            country_name = raw_country_code

    submission_payload = {
        key: value
        for key, value in form_data.items()
        if key not in _RESERVED_FIELD_NAMES and key != form.honeypot
    }
    if country_name:
        submission_payload["country_name"] = country_name

    # TODO(file uploads): request.form() returns UploadFile objects for any
    # <input type="file">. They currently pass straight into
    # submission_payload above, which will break DB persistence (a JSON
    # payload column can't serialize an UploadFile) the moment a customer's
    # form has a file field. Per your own note on the private-R2 plan:
    # stream each UploadFile to R2 under a per-submission key, keep the
    # bucket private, and store the R2 object key (not the bytes) in
    # submission_payload; generate a short-lived presigned GET URL only
    # when an authenticated dashboard user views that submission.

    db_form: FormDB | None = None
    if not isinstance(form, dict):
        db_form = form

    if db_form is not None:
        if not db_form.duplicate_allowed and db_form.duplicate_check_input:
            target_key = db_form.duplicate_check_input
            target_value = submission_payload.get(target_key)

            if target_value:
                # Query database for existing entries using PostgreSQL JSONB extraction styling: ->>
                dup_query = (
                    select(Submission)
                    .where(Submission.form_id == db_form.id)
                    .where(
                        Submission.payload[target_key].as_string() == str(target_value)
                    )
                )
                dup_result = await db.execute(dup_query)
                existing_submission = dup_result.scalar_one_or_none()

                if existing_submission:
                    # Block duplicate submissions and return a standard payload response error
                    return JSONResponse(
                        {
                            "error": f"Duplicate submission blocked. The field '{target_key}' has already been submitted."
                        },
                        status_code=status.HTTP_400_BAD_REQUEST,
                    )
        try:
            submission = Submission(form_id=db_form.id, payload=submission_payload)
            db.add(submission)
            await db.commit()
        except SQLAlchemyError as exc:
            await db.rollback()
            log.exception(f"Failed to persist submission for form {form_id}: {exc}")
            return JSONResponse({"error": "failed to save submission"}, status_code=500)

    # The submission is already saved above regardless of decision, so a
    # false-positive spam call isn't destructive — it just needs reviewing
    # in the dashboard. The visitor-facing response stays generic on
    # purpose: the old code returned {"status": "rejected", "reasons": [...]}
    # straight to the submitter, which hands a spammer exactly the feedback
    # they'd need to tune around your filter. If you want a spam-review tab
    # in the dashboard, persist `decision`/`reasons` onto the Submission row
    # here (not shown — depends on your schema) rather than relying on the
    # log line above.
    user_query = select(User).where(
        User.id
        == select(Project.user_id)
        .where(Project.id == form.project_id)
        .scalar_subquery()
    )

    # 2. Execute and pull the object out of the session
    result = await db.execute(user_query)
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(404, "user not found")
    background_task.add_task(
        EmailService().send_user_notification, user.email, form.name, form_data
    )
    return _finish(
        request,
        form_data,
        form,
        json_body={"status": "accepted"},
        status_code=200,
        redirect_ok=True,
    )


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
