from datetime import datetime, timedelta, timezone
import json
import uuid
from typing import Annotated, Optional

from fastapi import (
    APIRouter,
    Depends,
    Form,
    Header,
    HTTPException,
    Query,
    Request,
    Response,
    status,
)
from fastapi.responses import HTMLResponse, JSONResponse
from loguru import logger as log
from pydantic import ValidationError
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.db import get_db
from app.core.settings import settings
from app.core.templates import temp
from app.models.user import Form as FormDB, Project
from app.models.user import Submission, User
from app.models.user import CaptchaType
from app.routes.page import get_current_user
from app.schemas.form import FormSettingsPayload, NewForm, WidgetConfig
from app.services.form import (
    check_honeypot,
    check_rate_limit,
    check_user_agent,
    content_score,
    get_form_temp,
    make_altcha_challenge,
    route,
    sign_session,
    verify_bot_check,
    verify_session,
)

form_router = APIRouter()


def _build_form_context(form) -> dict:
    captcha_type = getattr(form, "captcha_type", None)
    captcha_value = getattr(captcha_type, "value", captcha_type) or form.get(
        "bot_provider", "cloudflare_turnstile"
    )

    honeypot_value = getattr(form, "honeypot", None) or form.get(
        "honeypot", settings.HONEYPOT_FIELD
    )

    if hasattr(form, "turnstile_sitekey"):
        turnstile_sitekey = form.turnstile_sitekey
        turnstile_secret = form.turnstile_secret
    else:
        turnstile_sitekey = form.get("turnstile_sitekey")
        turnstile_secret = form.get("turnstile_secret")

    return {
        "bot_provider": captcha_value,
        "honeypot": honeypot_value,
        "turnstile_sitekey": turnstile_sitekey,
        "turnstile_secret": turnstile_secret,
        "fields": {"name", "email", "message"},
        "required": {"name", "email", "message"},
    }


@form_router.post("/forms", response_class=HTMLResponse)
async def handle_create_form(
    request: Request,
    name: str = Form(...),
    project_id: str = Form(...),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    try:
        form = NewForm(name=name)

        query = select(FormDB).where(
            FormDB.project_id == project_id, FormDB.name == form.name
        )
        result = await db.execute(query)
        existing_form = result.scalar_one_or_none()

        if existing_form:
            # Option A: Trigger a failure Toast for HTMX without crashing the app
            trigger_payload = json.dumps(
                {"show-toast": f"Error: A form named '{form.name}' already exists!"}
            )
            return temp.TemplateResponse(
                request,
                "partials/duplicate_error.html",  # Keep this file completely blank
                {"request": request},
                headers={"HX-Trigger": trigger_payload},
                status_code=status.HTTP_200_OK,  # 200 tells HTMX to process the empty swap safely
            )

        new_form = FormDB(
            name=form.name,
            project_id=project_id,
            notification_email=user.email,
        )
        db.add(new_form)
        await db.commit()
        await db.refresh(new_form)

        trigger_payload = json.dumps(
            {"show-toast": f"Form '{new_form.name}' created successfully!"}
        )
        # return RedirectResponse(url="/projects", status_code=status.HTTP_303_SEE_OTHER)
        return temp.TemplateResponse(
            request,
            "form_card.html",
            {"request": request, "form": new_form, "project": {"id": project_id}},
            headers={
                "HX-Trigger": trigger_payload
            },  # 👈 HTMX automatically listens to this
        )

    except ValidationError as exc:
        log.warning(f"Failed to create new Form: {exc}")
        error_msg = exc.errors()[0]["msg"]
        log.warning(f"Validation failed for new form: {error_msg}")
        # Re-render the form page with the error message and the typed value
        return temp.TemplateResponse(
            request,
            "create_project_form.html",
            {
                "request": request,
                "error": error_msg,
                "typed_name": name,
            },
            status_code=status.HTTP_400_BAD_REQUEST,
        )
    except Exception as exc:
        log.error(f"Failed to create new form due to system error: {exc}")
        return temp.TemplateResponse(
            request,
            "projects.html",
            {"request": request, "error": "Something went wrong on our end."},
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )


@form_router.get("/projects/{project_id}/forms/{form_id}", response_class=HTMLResponse)
async def handle_get_project_form(
    request: Request,
    form_id: str,
    project_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    try:
        result = await db.execute(
            select(FormDB)
            .where(FormDB.id == form_id, FormDB.project_id == project_id)
            .options(selectinload(FormDB.submissions))
        )
        form = result.scalar_one_or_none()
        if not form:
            raise HTTPException(
                status_code=404, detail="Form configuration template not found."
            )

        # Fetch all saved dynamic submissions related to this specific form structure
        submissions_result = await db.execute(
            select(Submission)
            .where(Submission.form_id == form_id)
            .order_by(Submission.id.desc())  # Newest submissions first
        )
        submissions = submissions_result.scalars().all()
        return temp.TemplateResponse(
            request,
            "form.html",
            {
                "request": request,
                "form": form,
                "submissions": submissions,
                "email": user.email,
                "name": user.name,
                "user_id": user.id,
                "page": "projects",
            },
        )
    except Exception as e:
        log.exception(f"Something went wrong while fetching form details: {e}")


@form_router.get("/test-widget", response_class=HTMLResponse)
async def test_widget(request: Request):
    return temp.TemplateResponse(request, "test.html", {"request": request})


@form_router.get("/form/{formId}/config", response_model=WidgetConfig)
async def handle_form_config(
    request: Request,
    formId: str,
    db: AsyncSession = Depends(get_db),
):
    if not formId:
        return JSONResponse({"error": "unknown form"}, status_code=404)

    result = await db.execute(select(FormDB).where(FormDB.public_id == formId))
    form = result.scalar_one_or_none()
    if not form:
        form = get_form_temp(formId)
    if not form:
        return JSONResponse({"error": "unknown form"}, status_code=404)

    form_context = _build_form_context(form)
    provider = form_context["bot_provider"]
    base_url = str(settings.BASE_URL).rstrip("/")
    config = WidgetConfig(
        provider=provider,
        honeypotField=form_context["honeypot"],
        sessionToken=sign_session(formId),
        challengeUrl=f"{base_url}/form/{formId}/altcha-challenge",
        turnstileSitekey=form_context["turnstile_sitekey"]
        if provider == "cloudflare_turnstile"
        else None,
        success={
            "message": "Thanks! Your message has been sent successfully.",
            "redirect": None,
        },
    )

    if provider == "cloudflare_turnstile":
        config.challengeUrl = ""

    return config


@form_router.get("/form/{form_id}/altcha-challenge")
async def handle_altcha_challenge_create(
    request: Request,
    form_id: str,
    db: AsyncSession = Depends(get_db),
):
    query = select(FormDB).where(FormDB.public_id == form_id)
    result = await db.execute(query)
    form = result.scalar_one_or_none()

    if not form:
        form = get_form_temp(form_id)

    form_context = _build_form_context(form) if form else None
    if not form_context or form_context["bot_provider"] != "altcha":
        return JSONResponse(
            {"error": "altcha not enabled for this form"}, status_code=404
        )
    return make_altcha_challenge().to_dict()


@form_router.post("/form/{form_id}/submit")
async def handle_form_submit(
    form_id: str,
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
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
    token_value = form_data.get("sessionToken", "")

    if not isinstance(token_value, str):
        session_ok, session_err = False, "invalid session token format"
    else:
        session_ok, session_err = await verify_session(token_value, form_id)
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
        except Exception as exc:
            await db.rollback()
            log.exception(f"Failed to persist submission for form {form_id}: {exc}")
            return JSONResponse({"error": "failed to save submission"}, status_code=500)

    # --- content filter (scored, not hard-reject) ---
    score, reasons = await content_score(form_id, form_context, form_data)
    decision = route(score)

    if decision == "reject":
        return JSONResponse({"status": "rejected", "reasons": reasons}, status_code=200)

    return JSONResponse({"status": decision}, status_code=200)


@form_router.get("/forms", response_class=HTMLResponse)
async def handle_get_forms(
    request: Request,
    project_id: Optional[uuid.UUID] = None,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    try:
        # Fetch forms belonging to this user. Filter by project if provided.
        query = select(FormDB).where(FormDB.project_id == user.id)

        results = await db.execute(query)
        forms = results.scalars().all()

        return temp.TemplateResponse(
            request,
            "forms.html",
            {
                "forms": forms,
                "project_id": project_id,
                "email": user.email,
                "name": user.name,
                "user_id": user.id,
                "page": "forms",
            },
        )
    except Exception as e:
        log.warning(f"Error fetching Forms: {e}")
        raise HTTPException(status_code=500, detail="Internal Server Error")


# Formspree handles this beautifully by allowing an empty array [] or {"*"}
# to mean "Accept submissions from anywhere" during initial setup.
# Then, once the form receives its first submission,
# Formspree automatically locks the form to that specific domain to prevent spam,
# while allowing the user to manually add localhost or other staging domains later in their settings dashboard.
@form_router.put("/forms/{form_id}/settings")
async def handle_update_form_setting(
    request: Request,
    form_id: str,
    payload: FormSettingsPayload = Depends(FormSettingsPayload.as_form),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    try:
        query = select(FormDB).where(
            FormDB.id == form_id,
        )
        result = await db.execute(query)
        db_form = result.scalars().first()
        if not db_form:
            trigger_payload = json.dumps({"show-toast": "Error: Form not found!"})
            return temp.TemplateResponse(
                request,
                "partials/duplicate_error.html",  # Your blank file
                {"request": request},
                headers={"HX-Trigger": trigger_payload},
                status_code=status.HTTP_200_OK,
            )
        # 3. Parse comma-separated accepted domains into a list
        accepted_domains_raw = payload.allowed_domains
        accepted_domains_list = [
            d.strip() for d in accepted_domains_raw.split(",") if d.strip()
        ]
        # 4. Update existing form fields with the payload data
        db_form.name = payload.name.strip()
        db_form.honeypot = payload.honeypot
        db_form.notification_email = payload.notification_email
        db_form.redirect_url = payload.redirect_url if payload.redirect_url else None
        db_form.allowed_domains = accepted_domains_list
        db_form.captcha_type = payload.captcha_type
        if payload.captcha_type == CaptchaType.TURNSTILE:
            db_form.turnstile_sitekey = payload.turnstile_sitekey
            db_form.turnstile_secret = payload.turnstile_secret
        else:
            db_form.turnstile_sitekey = None
            db_form.turnstile_secret = None
        db_form.is_active = payload.is_active
        db_form.sub_message = payload.sub_message
        db_form.sub_bg_color = payload.sub_bg_color
        db_form.sub_txt_color = payload.sub_txt_color
        db_form.sub_lnk_color = payload.sub_lnk_color

        # 5. Commit changes to database
        await db.commit()
        await db.refresh(db_form)

        # 6. Return success template response or swap element
        success_trigger = json.dumps({"show-toast": "Settings updated successfully!"})
        return temp.TemplateResponse(
            request,
            "partials/duplicate_error.html",  # Change to your success partial
            {"request": request, "form": db_form},
            headers={"HX-Trigger": success_trigger},
            status_code=status.HTTP_200_OK,
        )

    except Exception as e:
        await db.rollback()
        # Handle or log server exception safely
        log.exception(f"Failed to update the form settings: Error {e}")
        error_trigger = json.dumps({"show-toast": "An unexpected error occurred."})
        return temp.TemplateResponse(
            request,
            "partials/duplicate_error.html",
            {"request": request},
            headers={"HX-Trigger": error_trigger},
            status_code=status.HTTP_200_OK,
        )


# --- 5. DELETE A FORM ---
@form_router.delete("/forms/{form_id}")
async def handle_delete_form(
    form_id: str,
    project_id: Annotated[str, Header(alias="X-Project-Id")],
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    try:
        # Explicit delete criteria safeguarding multi-tenant architecture
        print(project_id)
        stmt = (
            delete(FormDB)
            .where(FormDB.id == form_id, FormDB.project_id == project_id)
            .returning(FormDB.id)
        )
        result = await db.execute(stmt)
        deleted_id = result.scalar_one_or_none()
        if deleted_id is None:
            raise HTTPException(
                status_code=404, detail="Form asset not found or unauthorized."
            )

        await db.commit()

        # Ideal for HTMX delete operations (returns empty layout chunk, removing it from UI array)
        return Response(
            status_code=200, headers={"HX-Redirect": f"/projects/{project_id}"}
        )
    except HTTPException:
        raise
    except Exception as e:
        await db.rollback()
        log.error(f"Error executing form deletion payload: {e}")
        raise HTTPException(status_code=400, detail="Deletion runtime failure.")


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


async def _get_owned_form(db: AsyncSession, user: User, form_id: str) -> FormDB:
    form = await db.scalar(
        select(FormDB)
        .join(Project, FormDB.project_id == Project.id)
        .where(FormDB.id == form_id, Project.user_id == user.id)
    )
    if not form:
        # 🟢 Don't leak existence of forms belonging to other users — 404, not 403
        raise HTTPException(status_code=404, detail="Form not found")
    return form


async def _count_submissions(
    db: AsyncSession,
    form_id: str,
    start: datetime | None = None,
    end: datetime | None = None,
    status: str | None = None,
) -> int:
    query = select(func.count(Submission.id)).where(Submission.form_id == form_id)
    if start is not None:
        query = query.where(Submission.created_at >= start)
    if end is not None:
        query = query.where(Submission.created_at < end)
    if status is not None:
        query = query.where(Submission.status == status)
    return await db.scalar(query) or 0


def _pct_change(current: int, previous: int) -> dict:
    """Handles the zero-previous-period case instead of dividing by zero,
    which a brand-new form would hit immediately."""
    if previous == 0:
        if current == 0:
            return {"direction": "flat", "value": 0, "label": "No change"}
        return {"direction": "up", "value": None, "label": "New activity"}
    delta = ((current - previous) / previous) * 100
    return {
        "direction": "up" if delta >= 0 else "down",
        "value": round(abs(delta), 1),
        "label": None,
    }


async def _get_form_analytics(db: AsyncSession, form: FormDB, range_days: int) -> dict:
    now = datetime.now(timezone.utc)
    period_start = now - timedelta(days=range_days)
    prev_period_start = now - timedelta(days=range_days * 2)

    # Lifetime totals (not scoped to the selected range)
    total_submissions = await _count_submissions(db, form.id)

    # This-period vs previous-period volume
    submissions_this_period = await _count_submissions(db, form.id, start=period_start)
    submissions_prev_period = await _count_submissions(
        db, form.id, start=prev_period_start, end=period_start
    )
    submissions_change = _pct_change(submissions_this_period, submissions_prev_period)

    # Spam blocked in the selected range, broken down by provider
    spam_blocked = await _count_submissions(
        db, form.id, start=period_start, status="rejected"
    )
    rejected_prev_period = await _count_submissions(
        db, form.id, start=prev_period_start, end=period_start, status="rejected"
    )

    spam_provider_query = await db.execute(
        select(Submission.spam_provider, func.count(Submission.id))
        .where(Submission.form_id == form.id)
        .where(Submission.status == "rejected")
        .where(Submission.created_at >= period_start)
        .group_by(Submission.spam_provider)
    )
    spam_by_provider = {
        str(row[0] or "other"): int(row[1]) for row in spam_provider_query.all()
    }

    # ------------------------------------------------------------------
    # Conversion rate = accepted / (accepted + rejected) for the period.
    # NOTE: proxy metric only — there's no impression/pageview tracking,
    # so this can't reflect true visit-to-submit conversion yet. It's
    # really "% of incoming traffic that passed spam filtering."
    # ------------------------------------------------------------------
    def _conversion_rate(accepted: int, rejected: int) -> float | None:
        total = accepted + rejected
        return round((accepted / total) * 100, 1) if total else None

    accepted_this_period = submissions_this_period - spam_blocked
    accepted_prev_period = submissions_prev_period - rejected_prev_period

    conversion_rate = _conversion_rate(accepted_this_period, spam_blocked)
    conversion_rate_prev = _conversion_rate(accepted_prev_period, rejected_prev_period)
    conversion_change = (
        round(conversion_rate - conversion_rate_prev, 1)
        if conversion_rate is not None and conversion_rate_prev is not None
        else None
    )

    # Daily trend for the bar chart, scoped to this form only
    trend = []
    for i in reversed(range(range_days)):
        day_date = (now - timedelta(days=i)).date()
        day_start = datetime.combine(day_date, datetime.min.time(), tzinfo=timezone.utc)
        day_end = day_start + timedelta(days=1)
        count = await _count_submissions(db, form.id, start=day_start, end=day_end)
        trend.append(
            {
                "label": day_date.strftime("%a"),
                "date": day_date.strftime("%b %d"),
                "count": count,
            }
        )

    max_count = max((d["count"] for d in trend), default=0)
    for d in trend:
        d["height_pct"] = round((d["count"] / max_count) * 100, 1) if max_count else 0

    return {
        "total_submissions": total_submissions,
        "submissions_change": submissions_change,
        "spam_blocked": spam_blocked,
        "spam_by_provider": spam_by_provider,
        "conversion_rate": conversion_rate,
        "conversion_change": conversion_change,
        "trend": trend,
        "range_days": range_days,
    }


@form_router.get("forms/{form_id}/analytics")
async def handle_form_analytics(
    form_id: str,
    request: Request,
    range: int = Query(7, ge=1, le=90, alias="range"),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    form = await _get_owned_form(db, user, form_id)

    analytics = await _get_form_analytics(db, form, range_days=range)

    return temp.TemplateResponse(
        request,
        "form_analytics.html",
        {
            "form": form_id,
            **analytics,
        },
    )
