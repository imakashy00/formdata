import json
import uuid
from loguru import logger as log
from typing import Optional


from fastapi import APIRouter, Depends, Form, HTTPException, Request, status
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from loguru import logger as log
from pydantic import ValidationError
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.db import get_db
from app.core.settings import settings
from app.core.templates import temp
from app.models.user import Form as FormDB
from app.models.user import Submission, User
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
    verify_altcha,
    verify_bot_check,
    verify_session,
    verify_turnstile,
)

form_router = APIRouter()


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
        new_form = FormDB(
            name=form.name,
            project_id=project_id,
        )
        db.add(new_form)
        await db.commit()
        await db.refresh(new_form)

        trigger_payload = json.dumps(
            {"showToast": f"Form '{new_form.name}' created successfully!"}
        )
        # return RedirectResponse(url="/projects", status_code=status.HTTP_303_SEE_OTHER)
        return temp.TemplateResponse(
            request,
            "form_card.html",
            {
                "request": request,
                "form": new_form,
            },
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
async def handle_form_config(request: Request, formId: str):
    print(formId)
    # form = get_form(form_id=formId)
    if not formId:
        return JSONResponse({"error": "unknown form"}, status_code=404)

    token = "sdkjfslfjsdlkfjsdlkfjsdlkfjlsdkfjlsdjf"
    config = WidgetConfig(
        provider="altcha",
        honeypotField="website",
        sessionToken=token,
        challengeUrl=f"http://localhost:8000/form/{formId}/altcha-challenge",
        success={
            "message": "Thanks! Your message has been sent successfully.",
            "redirect": None,  # Keep them on the same page
        },
    )
    # if form["bot_provider"] == "altcha":
    #         config.challengeUrl = f"http://localhost:8000/form/{formId}/altcha-challenge"
    #     elif form["bot_provider"] == "turnstile":
    #         config.turnstileSitekey = form["turnstile_sitekey"]

    return config


@form_router.get("/form/{form_id}/altcha-challenge")
async def handle_altcha_challenge_create(request: Request, form_id: str):
    form = get_form_temp(form_id)
    if not form or form["bot_provider"] != "altcha":
        return JSONResponse(
            {"error": "altcha not enabled for this form"}, status_code=404
        )
    return make_altcha_challenge().to_dict()


@form_router.post("/form/{form_id}/submit")
async def handle_form_submit(form_id: str, request: Request):
    form = get_form_temp(form_id)
    if not form:
        return JSONResponse({"error": "unknown form"}, status_code=404)

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

    if not check_honeypot(form_data):
        # Bots that fill every field trip this. Respond as if successful —
        # no need to teach the bot what tripped it.
        return JSONResponse({"status": "accepted"}, status_code=200)

    missing = form["required"] - form_data.keys()
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
    bot_ok, bot_err = await verify_bot_check(form, form_data, request)
    if not bot_ok:
        return JSONResponse({"error": f"bot check failed: {bot_err}"}, status_code=400)

    # --- content filter (scored, not hard-reject) ---
    score, reasons = await content_score(form_id, form, form_data)
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


@form_router.put("/forms/{form_id}/settings")
async def handle_update_form_setting(
    request: Request,
    form_id: str,
    payload: FormSettingsPayload = Depends(FormSettingsPayload.as_form),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    try:
        settings_dict = payload.model_dump()
        print(settings_dict)
        # Parse comma-separated domains into a clean python list
        # allowed_domains = []
        # print(form_id)
        # if allowed_domains_raw:
        #     allowed_domains = [
        #         d.strip() for d in allowed_domains_raw.split(",") if d.strip()
        #     ]

        # # Instantiate database record
        # new_form = Form(
        #     user_id=user.id,
        #     name=name,
        #     allowed_domains=allowed_domains,
        #     redirect_url=redirect_url if redirect_url else None,
        #     notification_email=notification_email
        #     if notification_email
        #     else user.email,  # default to user email
        #     use_honeypot=use_honeypot,
        #     hcaptcha_secret_key=hcaptcha_secret_key if hcaptcha_secret_key else None,
        # )

        # db.add(new_form)
        # await db.commit()

        # Redirect back to forms index view after creation
        return RedirectResponse(url="/forms", status_code=status.HTTP_303_SEE_OTHER)

    except Exception as e:
        await db.rollback()
        log.error(f"Error creating form: {e}")
        raise HTTPException(status_code=400, detail="Could not create form wrapper.")


# --- 5. DELETE A FORM ---
@form_router.delete("/forms/{form_id}")
async def handle_delete_form(
    form_id: uuid.UUID,
    project_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    try:
        # Explicit delete criteria safeguarding multi-tenant architecture
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
        return HTMLResponse(content="", status_code=200)

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
