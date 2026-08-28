import os
import uuid
from functools import lru_cache
from typing import Annotated
from urllib.parse import parse_qsl, urlencode, urlparse

import pycountry
from fastapi import Depends, Request, Response, status
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from loguru import logger as log
from requests.compat import urlunparse
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from starlette.datastructures import FormData, UploadFile

from app.core.db import get_db
from app.core.settings import settings
from app.models.user import Form as FormDB
from app.models.user import Project, Submission, SubmissionStatus, User
from app.services.file_upload import (
    DANGEROUS_EXTENSIONS,
    RejectedFile,
    upload_submission_files_batch,
)
from app.services.form import verify_bot_check

# `_error_url` was previously missing here, which meant it could leak into
# the stored submission payload as if it were a real form field.
_RESERVED_FIELD_NAMES = {"cf-turnstile-response", "_next", "_error_url"}


def _split_form_data(
    raw_form: FormData,
) -> tuple[dict[str, str | list], dict[str, list[UploadFile]]]:
    fields: dict[str, str | list] = {}
    files: dict[str, list[UploadFile]] = {}

    for key, value in raw_form.multi_items():
        if isinstance(value, UploadFile):
            files.setdefault(key, []).append(value)
        else:
            if key in fields:
                current = fields[key]

                if isinstance(current, list):
                    current.append(value)
                else:
                    fields[key] = [current, value]
            else:
                fields[key] = value

    return fields, files


def _safe_redirect_target(
    candidate: str | None, request: Request, form: FormDB
) -> str | None:

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
    form,
    *,
    json_body: dict,
    status_code: int,
    redirect_ok: bool,
    token: str | None = None,  # Add token argument
) -> Response:
    """Content-negotiated response.

    JS/fetch integrations send `Accept: application/json` and get JSON back.
    Plain <form> posts get a 303 redirect back to the customer's custom URL
    or fall back to our application's template thank-you route.
    """
    wants_json = "application/json" in request.headers.get("accept", "")
    if wants_json:
        return JSONResponse(json_body, status_code=status_code)

    if redirect_ok:
        # Check if the user specified a custom redirect target (_next URL)
        target = _resolve_redirect_target(form_data, request, form)

        # If no custom redirect URL is provided, fall back to our platform's thank-you path
        if not target and token:
            # Reconstructs absolute path to your dynamic /{form_id}/thank-you/{token} route
            base_url = str(request.base_url).rstrip("/")
            target = f"{base_url}/client-forms/{form.public_id}/thank-you/{token}"  # Match your exact prefix router mount

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
        select(User)
        .join(Project, User.id == Project.user_id)
        .join(FormDB, FormDB.project_id == Project.id)
        .where(FormDB.public_id == form_id)
        .options(selectinload(User.subscription))  # <-- Uses selectinload
    )

    result = await db.execute(query)
    return result.scalar_one_or_none()


async def parse_request_data(request: Request):
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
            max_files=settings.MAX_FILES_PER_SUBMISSION,
            max_part_size=settings.MAX_UPLOAD_BYTES,
        )
        form_data, files = _split_form_data(raw_form)
    return form_data, files


def check_dangerous_file_type(files):
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


async def process_and_upload_files(
    files: dict[str, list[UploadFile]],
    form_id: str,
    submission_payload: dict,
) -> JSONResponse | str:
    """
    Batches and uploads submission files, then attaches their metadata to the payload.

    Returns:
        The submission_ref (str) if successful, or a JSONResponse on error.
    """

    submission_ref = uuid.uuid4().hex
    flat_files = [
        (field_name, upload)
        for field_name, uploads in files.items()
        for upload in uploads
    ]

    try:
        log.info("Going to upload files 🗂️...")
        uploaded = await upload_submission_files_batch(
            form_id=form_id,
            submission_ref=submission_ref,
            files=flat_files,
            max_bytes=settings.MAX_UPLOAD_BYTES,
        )
    except (RejectedFile, ValueError) as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)
    except Exception as exc:
        log.exception(f"File upload failed for form {form_id}: {exc}")
        return JSONResponse(
            {"error": "failed to upload attachment(s)"}, status_code=502
        )

    for field_name, metas in uploaded.items():
        submission_payload[field_name] = metas if len(metas) > 1 else metas[0]

    return submission_ref


async def handle_bot_verification(
    form_data: dict,
    files: dict[str, list[UploadFile]],
    request: Request,
    form,
    db,
):
    # --- bot verification: honeypot above + Cloudflare Turnstile here ---
    bot_ok, bot_err = await verify_bot_check(form_data, request, form.turnstile_secret)
    if not bot_ok:
        log.debug(f"Turnstile rejected form {form.id} submission: {bot_err}")

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
            log.exception(f"Failed to persist spam row for form {form.id}: {exc}")
            # Don't break the client response flow if spam tracking fails

        accept_header = request.headers.get("accept", "")
        is_json_request = (
            request.headers.get("content-type", "").startswith("application/json")
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
