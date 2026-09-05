import asyncio
import hashlib
import secrets
from datetime import UTC, datetime, timedelta
from typing import Annotated
from uuid import UUID

from asyncpg import InternalServerError
from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    HTTPException,
    Request,
    status,
)
from fastapi.responses import JSONResponse
from loguru import logger as log
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.core.errors import NotFoundError
from app.core.settings import settings
from app.core.templates import temp
from app.models.user import Form as FormDB
from app.models.user import Project, Submission, Subscription, ThankYouToken, User
from app.repositories.client_form_repository import ClientFormRepository
from app.schemas.user import SubscriptionStatus
from app.services.bill_calculation import TRIAL_SUBMISSION_LIMIT
from app.services.client_form import (
    _build_submission_payload,
    _finish,
    check_dangerous_file_type,
    get_form_owner,
    handle_bot_verification,
    parse_request_data,
    process_and_upload_files,
)
from app.services.email_service import deliver_customer_autoresponder
from app.services.file_upload import (
    delete_submission_file,
)
from app.services.form import (
    check_honeypot,
    check_user_agent,
)
from app.services.submission_sync import (
    build_pending_sync_status,
    sync_submission_integrations,
)

MAX_UPLOAD_BYTES = settings.MAX_UPLOAD_BYTES  # 10 MB/file
MAX_FILES_PER_SUBMISSION = settings.MAX_FILES_PER_SUBMISSION

client_form_router = APIRouter(prefix="/f")

# How to Send an Autoresponse to the Submitter
# 1. Include an email field in your HTML form (usually named email or _replyto) so Formspree knows where to send the message.
# 2. Go to your Formspree dashboard and open your form settings.
# 3. Navigate to the Plugins or Emails tab and add the Autoresponses feature.
# 4. Write your custom confirmation text, subject line, and sender name.
# 4. Save your changes to enable automatic replies for future submissions.
# 5. Explore the official documentation on Formspree Autoresponses.
# 6. Read a guide on building a Formspree Registration Form with autoresponses.


def create_token(submission_id: UUID) -> tuple[str, str]:
    # This is what goes into the URL query/path
    raw_token = secrets.token_urlsafe(32)
    # This is what goes into the database for secure lookup
    hashed_token = hashlib.sha256(raw_token.encode()).hexdigest()
    return raw_token, hashed_token


@client_form_router.post("/{form_id}")
async def handle_form_submit(
    form_id: str,
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
    background_task: BackgroundTasks,
    form_owner: Annotated[User, Depends(get_form_owner)],
):
    if not form_owner:
        raise HTTPException(404, "User not found...")
    if not form_owner.has_access:
        # Maybe redirect to a formdata page with message
        raise HTTPException(403, "Form Owner is not subscribed.")

    subscription = form_owner.subscription

    form = await ClientFormRepository(db).get_form_with_public_id(form_id)
    if not form:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Form Not found"
        )

    # --- fast structural checks ---
    if not check_user_agent(request):
        return JSONResponse({"error": "missing user agent"}, status_code=400)

    parsed_result = await parse_request_data(request)
    if isinstance(parsed_result, JSONResponse):
        return parsed_result
    form_data, files = parsed_result
    honeypot_field = form.honeypot
    if not check_honeypot(form_data, honeypot_field):
        # Bots that fill every field trip this. Respond exactly like a normal success
        return _finish(
            request,
            form_data,
            form,
            json_body={"status": "accepted"},
            status_code=status.HTTP_200_OK,
            redirect_ok=form.redirect,
        )

    required_fields = set(getattr(form, "required_fields", None) or ())
    missing = required_fields - form_data.keys()
    if missing:
        return JSONResponse(
            {"error": f"missing fields: {sorted(missing)}"}, status_code=400
        )

    dangerous_file_error = check_dangerous_file_type(files)
    if isinstance(dangerous_file_error, JSONResponse):
        return dangerous_file_error
    if form.turnstile_enabled:
        await handle_bot_verification(form_data, files, request, form, db)

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
    log.info(f"Files{files}")
    if files:
        upload_result = await process_and_upload_files(
            files, form_id, submission_payload
        )
        if isinstance(upload_result, JSONResponse):
            return upload_result
    enabled_integrations = await ClientFormRepository(db).get_enabled_integrations(
        str(form.id)
    )
    try:
        locked_subscription = await db.scalar(
            select(Subscription)
            .where(Subscription.user_id == form_owner.id)
            .with_for_update()
        )
        if locked_subscription:
            subscription = locked_subscription
            if (
                subscription.status == SubscriptionStatus.TRIAL.value
                and subscription.submissions_used >= TRIAL_SUBMISSION_LIMIT
            ):
                await db.rollback()
                raise HTTPException(
                    403,
                    "Your 1,000 free trial submissions have been used. Upgrade to keep collecting submissions.",
                )

        submission = Submission(
            form_id=form.id, payload=submission_payload, country=country_name
        )
        if enabled_integrations:
            submission.integration_sync_status = build_pending_sync_status(
                enabled_integrations
            )
        db.add(submission)
        if subscription:
            subscription.submissions_used += 1
        await db.flush()
        raw_token, token_hash = create_token(submission.id)
        db.add(
            ThankYouToken(
                token_hash=token_hash,
                submission_id=submission.id,
                expires_at=datetime.now(UTC) + timedelta(minutes=5),
            )
        )
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

    if enabled_integrations:
        background_task.add_task(sync_submission_integrations, str(submission.id))
    if form.autoresponse and form.autoresponse_recipient_key:
        background_task.add_task(
            deliver_customer_autoresponder,
            submission_payload,
            form.autoresponse_recipient_key,
            form.name,
            form.customer_subject,
            form.customer_body,
        )

    return _finish(
        request,
        form_data,
        form,
        json_body={"status": "accepted"},
        status_code=status.HTTP_200_OK,
        redirect_ok=form.redirect,
        token=raw_token,
    )


@client_form_router.get("/{form_id}/thank-you/{token}")
async def handle_form_submit_sucess(
    request: Request,
    token: str,
    form_id: str,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    # Need to find out

    token_hash = hashlib.sha256(token.encode()).hexdigest()

    result = await db.execute(
        select(ThankYouToken).where(ThankYouToken.token_hash == token_hash)
    )

    thank_you_token = result.scalar_one_or_none()

    if not thank_you_token:
        raise NotFoundError("Submission not found")

    if thank_you_token.used_at is not None:
        raise NotFoundError("Submission not found")

    if thank_you_token.expires_at < datetime.now(UTC):
        raise InternalServerError("Something went wrong")

    submission = await db.get(
        Submission,
        thank_you_token.submission_id,
    )

    if not submission:
        raise HTTPException(status_code=404)

    thank_you_token.used_at = datetime.now(UTC)

    try:
        await db.commit()
    except SQLAlchemyError:
        await db.rollback()
        # Keep moving so the user still gets their template visual even if the database sync fails
    query = select(FormDB).where(FormDB.public_id == form_id)
    result = await db.execute(query)
    form = result.scalar_one_or_none()
    if not form:
        return temp.TemplateResponse(request, name="submission_error.html")
    return temp.TemplateResponse(
        request=request,
        name="submission_sucess.html",
        context={"submission": submission, "form": form},
    )
