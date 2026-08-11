import asyncio
import os
import uuid
from functools import lru_cache
from typing import Annotated
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

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
from starlette.datastructures import UploadFile

from app.core.db import get_db
from app.core.settings import settings
from app.models.user import Form as FormDB
from app.models.user import Project, Submission, SubmissionStatus, User
from app.services.email_service import EmailService
from app.services.file_upload import (
    DANGEROUS_EXTENSIONS,
    RejectedFile,
    delete_submission_file,
    upload_submission_files_batch,
)
from app.services.form import (
    check_honeypot,
    check_rate_limit,
    check_user_agent,
    verify_bot_check,
)

# `_error_url` was previously missing here, which meant it could leak into
# the stored submission payload as if it were a real form field.
_RESERVED_FIELD_NAMES = {"cf-turnstile-response", "_next", "_error_url"}


MAX_UPLOAD_BYTES = settings.MAX_UPLOAD_BYTES  # 10 MB/file
MAX_FILES_PER_SUBMISSION = settings.MAX_FILES_PER_SUBMISSION

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


def _split_form_data(
    raw_form,
) -> tuple[dict[str, str | list], dict[str, list[UploadFile]]]:
    """Split Starlette's multi-dict FormData into plain text fields and
    file uploads, without silently dropping repeated keys.

    dict(await request.form()) keeps only the *last* value for any field
    name submitted more than once — this fixes that for both text fields
    (checkboxes, multi-selects) and file fields. Any key whose values are
    UploadFile objects is treated as a file field, so this handles both
    a single <input type="file" multiple> field AND several distinctly
    named file inputs in the same submission — each field just becomes an
    entry in `files` keyed by its own name.
    """
    fields: dict[str, str | list] = {}
    files: dict[str, list[UploadFile]] = {}
    for key in raw_form:
        values = raw_form.getlist(key)
        if any(isinstance(v, UploadFile) for v in values):
            files[key] = [v for v in values if isinstance(v, UploadFile)]
        else:
            fields[key] = values[0] if len(values) == 1 else list(values)
    return fields, files


def _safe_redirect_target(
    candidate: str | None, request: Request, form: FormDB
) -> str | None:
    """Relative paths are always fine. Absolute URLs are only allowed if
    they match the form's configured domain or the page that submitted to
    us — otherwise this is an open-redirect gadget.

    Previously only `_next` went through this check; `_error_url` (used on
    a failed Turnstile check) had no validation at all. Both now share
    this one guard.
    """
    if not isinstance(candidate, str) or not candidate:
        return None
    parsed = urlparse(candidate)
    if not parsed.netloc:
        if candidate.startswith("/"):
            return candidate
        return None

    referer = request.headers.get("referer")
    referer_host = urlparse(referer).netloc if referer else None
    allowed_host = form.allowed_domains[0] if form.allowed_domains else None
    if parsed.netloc in {allowed_host, referer_host}:
        return candidate

    log.warning(f"Ignoring untrusted redirect target: {candidate!r}")
    return None


def _resolve_redirect_target(
    form_data: dict, request: Request, form: FormDB
) -> str | None:
    """Where to send the visitor's browser after a plain (non-AJAX) form
    POST. Mirrors Formspree's `_next` convention."""
    target = _safe_redirect_target(form_data.get("_next"), request, form)
    return target or request.headers.get("referer")


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


@lru_cache(maxsize=256)
def _country_name(alpha_2: str) -> str:
    """pycountry.countries.get() walks a small in-memory table — cheap, but
    not free, and it's the same ~250 possible lookups on every single
    request. Caching removes the repeat work entirely."""
    country = pycountry.countries.get(alpha_2=alpha_2)
    return country.name if country else alpha_2


def _resolved_country(request: Request) -> str | None:
    raw = request.headers.get("cf-ipcountry")
    return _country_name(raw.upper()) if raw else None


def _build_submission_payload(
    form_data: dict, form: FormDB, request: Request
) -> tuple[dict, str | None]:
    """Text-field payload with reserved/honeypot fields stripped and
    country resolved. File fields are merged in by the caller after
    upload. Used for both the accepted path and the rejected/spam path —
    previously this logic (and the country lookup) was duplicated between
    the two, which is how the accepted path ended up never setting
    `country` on the Submission row while the rejected path did."""
    payload = {
        key: value
        for key, value in form_data.items()
        if key not in _RESERVED_FIELD_NAMES and key != form.honeypot
    }
    country_name = _resolved_country(request)
    if country_name:
        payload["country_name"] = country_name
    return payload, country_name


async def get_form_owner(form_id: str, db: Annotated[AsyncSession, Depends(get_db)]):
    query = (
        select(Project.user_id)
        .join(FormDB, FormDB.project_id == Project.id)
        .where(FormDB.project_id == form_id)
    )
    result = await db.execute(query)
    return result.scalar_one_or_none()


@client_form_router.post("/{form_id}")
async def handle_form_submit(
    form_id: str,
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
    background_task: BackgroundTasks,
    form_owner: Annotated[User, Depends(get_form_owner)],
):
    if not form_owner.has_access:
        # Maybe redirect to a formdata page with message
        raise HTTPException(403, "Form Owner is not subscribed.")

    query = select(FormDB).where(FormDB.public_id == form_id)
    result = await db.execute(query)
    form = result.scalar_one_or_none()

    if not form:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Form Not found"
        )

    # --- edge-equivalent: rate limiting ---
    # Independent checks against different keys -> run concurrently instead
    # of two sequential awaits. Trade-off: an IP that's already over its
    # limit now still costs one extra rate-limit-store round trip (the old
    # code short-circuited before checking the form-level limit). Worth
    # reverting to sequential if limited IPs are a large fraction of your
    # traffic and store load matters more than latency here.
    ip = _client_ip(request)
    ip_ok, form_ok = await asyncio.gather(
        check_rate_limit("ip", ip, *settings.RATE_LIMIT_IP),
        check_rate_limit("form", form_id, *settings.RATE_LIMIT_FORM),
    )
    if not ip_ok:
        return JSONResponse({"error": "rate limit exceeded"}, status_code=429)
    if not form_ok:
        return JSONResponse(
            {"error": "form is receiving too many submissions"}, status_code=429
        )

    # --- fast structural checks ---
    if not check_user_agent(request):
        return JSONResponse({"error": "missing user agent"}, status_code=400)

    content_type = request.headers.get("content-type", "")
    files: dict[str, list[UploadFile]] = {}
    if content_type.startswith("application/json"):
        # fetch()-based integrations (React, Vue, custom JS) typically send
        # JSON rather than form-encoded data. JSON bodies can't carry files
        # — an integration that needs uploads must use multipart/form-data.
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
        # x-www-form-urlencoded) — what WordPress/plain-HTML embeds send,
        # and the only way file uploads arrive. max_files/max_part_size
        # let Starlette reject an oversized/too-large submission while
        # streaming it, instead of after fully buffering it in memory.
        raw_form = await request.form(
            max_files=MAX_FILES_PER_SUBMISSION,
            max_part_size=MAX_UPLOAD_BYTES,
        )
        form_data, files = _split_form_data(raw_form)

    honeypot_field = form.honeypot

    if not check_honeypot(form_data, honeypot_field):
        # Bots that fill every field trip this. Respond exactly like a
        # normal success — including the redirect — so there's nothing
        # for the bot (or whoever's watching its logs) to learn from, and
        # skip uploading its files to R2 entirely — no reason to spend
        # bandwidth/storage on confirmed spam.
        return _finish(
            request,
            form_data,
            form,
            json_body={"status": "accepted"},
            status_code=200,
            redirect_ok=True,
        )

    required_fields = set(getattr(form, "required_fields", None) or ())
    missing = required_fields - form_data.keys()
    if missing:
        return JSONResponse(
            {"error": f"missing fields: {sorted(missing)}"}, status_code=400
        )

    # Cheap, in-memory check before any network I/O: an obviously dangerous
    # file type is rejected before we spend a Turnstile round trip or a
    # single byte of R2 bandwidth on it.
    for field_name, uploads in files.items():
        for upload in uploads:
            ext = os.path.splitext(upload.filename or "")[1].lower()
            if ext in DANGEROUS_EXTENSIONS:
                return JSONResponse(
                    {"error": f"'{field_name}': file type '{ext}' is not allowed"},
                    status_code=400,
                )

    # --- bot verification: honeypot above + Cloudflare Turnstile here ---
    bot_ok, bot_err = await verify_bot_check(form_data, request, form.turnstile_secret)
    if not bot_ok:
        log.debug(f"Turnstile rejected form {form_id} submission: {bot_err}")

        submission_payload, country_name = _build_submission_payload(
            form_data, form, request
        )
        # Files aren't uploaded for a confirmed-bot submission, but note
        # what was withheld so the spam-review dashboard still shows the
        # field existed.
        for field_name, uploads in files.items():
            submission_payload[field_name] = [
                {"filename": u.filename, "skipped": "bot verification failed"}
                for u in uploads
            ]

        try:
            db.add(
                Submission(
                    form_id=form.id,
                    payload=submission_payload,
                    status=SubmissionStatus.REJECTED,  # spam dashboard review view
                    opened=False,
                    country=country_name,
                )
            )
            await db.commit()
        except SQLAlchemyError as exc:
            await db.rollback()
            log.exception(f"Failed to persist spam row for form {form_id}: {exc}")
            # Don't break the client response flow if spam tracking fails

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

        # Traditional native <form> action redirect handling fallback.
        # `_error_url` now goes through the same open-redirect guard as
        # `_next` (it previously had none).
        error_redirect_url = _safe_redirect_target(
            str(form_data.get("_error_url")), request, form
        ) or request.headers.get("referer")

        if error_redirect_url:
            parsed_url = urlparse(error_redirect_url)
            query_params = dict(parse_qsl(parsed_url.query))
            query_params["error"] = "turnstile_failed"
            # NOTE: the previous version built `query_params` with the
            # error flag injected but then passed "" as the query
            # component into urlunparse, discarding it — the redirect
            # never actually carried ?error=turnstile_failed. Fixed by
            # re-encoding query_params instead of dropping it.
            final_redirect_url = urlunparse(
                (
                    parsed_url.scheme,
                    parsed_url.netloc,
                    parsed_url.path,
                    parsed_url.params,
                    urlencode(query_params),
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

    submission_payload, country_name = _build_submission_payload(
        form_data, form, request
    )

    if not form.duplicate_allowed and form.duplicate_check_input:
        target_key = form.duplicate_check_input
        target_value = submission_payload.get(target_key)
        if target_value:
            # PostgreSQL JSONB extraction: ->>
            dup_query = (
                select(Submission)
                .where(Submission.form_id == form.id)
                .where(Submission.payload[target_key].as_string() == str(target_value))
            )
            dup_result = await db.execute(dup_query)
            if dup_result.scalar_one_or_none():
                # Block duplicates before we ever touch R2 — no reason to
                # upload files for a submission we're about to reject.
                return JSONResponse(
                    {
                        "error": f"Duplicate submission blocked. The field '{target_key}' has already been submitted."
                    },
                    status_code=status.HTTP_400_BAD_REQUEST,
                )

    # --- upload files: concurrently, sharing one R2 connection, only now
    # that we know this submission isn't spam or a duplicate ---
    uploaded: dict[str, list[dict]] = {}
    if files:
        submission_ref = uuid.uuid4().hex
        flat_files = [
            (field_name, upload)
            for field_name, uploads in files.items()
            for upload in uploads
        ]
        try:
            uploaded = await upload_submission_files_batch(
                form_id=form_id,
                submission_ref=submission_ref,
                files=flat_files,
                max_bytes=MAX_UPLOAD_BYTES,
            )
        except RejectedFile as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)
        except ValueError as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)
        except Exception as exc:
            log.exception(f"File upload failed for form {form_id}: {exc}")
            return JSONResponse(
                {"error": "failed to upload attachment(s)"}, status_code=502
            )

        for field_name, metas in uploaded.items():
            submission_payload[field_name] = metas if len(metas) > 1 else metas[0]

    try:
        submission = Submission(
            form_id=form.id, payload=submission_payload, country=country_name
        )
        db.add(submission)
        await db.commit()
    except SQLAlchemyError as exc:
        await db.rollback()
        log.exception(f"Failed to persist submission for form {form_id}: {exc}")
        # Files are already sitting in R2 at this point — clean them up so
        # a DB failure doesn't leave orphaned objects nothing points to.
        if uploaded:
            await asyncio.gather(
                *(
                    delete_submission_file(m["r2_key"])
                    for metas in uploaded.values()
                    for m in metas
                ),
                return_exceptions=True,
            )
        return JSONResponse({"error": "failed to save submission"}, status_code=500)

    user_query = select(User).where(
        User.id
        == select(Project.user_id)
        .where(Project.id == form.project_id)
        .scalar_subquery()
    )
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
