from functools import lru_cache
from typing import Annotated
from urllib.parse import urlparse

import pycountry
from fastapi import Depends, Request, Response
from fastapi.responses import JSONResponse, RedirectResponse
from loguru import logger as log
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from starlette.datastructures import UploadFile

from app.core.db import get_db
from app.models.user import Form as FormDB
from app.models.user import Project, User

# `_error_url` was previously missing here, which meant it could leak into
# the stored submission payload as if it were a real form field.
_RESERVED_FIELD_NAMES = {"cf-turnstile-response", "_next", "_error_url"}


def _split_form_data(
    raw_form,
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
        select(User)
        .join(Project, User.id == Project.user_id)
        .join(FormDB, FormDB.project_id == Project.id)
        .where(FormDB.public_id == form_id)
        .options(selectinload(User.subscription))  # <-- Uses selectinload
    )

    result = await db.execute(query)
    return result.scalar_one_or_none()
