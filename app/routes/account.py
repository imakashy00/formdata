from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.core.settings import settings
from app.core.templates import temp
from app.models.user import Form as FormDB
from app.models.user import Project, Submission, User
from app.schemas.user import SubscriptionStatus
from app.services.account import get_customer_portal_links
from app.services.dependencies import current_user

account_router = APIRouter()

# Single source of truth for Paddle price IDs <-> internal plan names.
# Mirrors the PLANS object in account.html's <script> block — consider moving
# both to one shared config module so the two can never drift apart.
PRICE_ID_TO_PLAN = {
    "pri_01kwhvxjre9b0hbjvnfwhe69bp": "solo",
    "pri_01kz9pnhgpaz1qkafrypwmm20b": "studio",
}

# Monthly submission allowances per plan (mirrors the copy on the pricing
# cards in account.html: "1,000 submissions / month" / "2,000 / month").
PLAN_SUBMISSION_QUOTAS = {
    "solo": 1000,
    "studio": 2000,
}
DEFAULT_TRIAL_QUOTA = 200  # adjust to whatever your trial actually allows

# Storage is a Studio-only feature per the pricing cards ("File uploads" is
# an X on Solo). 2GB baseline is included; extra is billed at $1/GB/month,
# but there's no column yet tracking purchased extra storage — see note below.
PLAN_STORAGE_LIMITS_BYTES = {
    "studio": 2 * 1024**3,
}


def _format_date(value: datetime | None) -> str | None:
    """'Aug 20, 2026' — matches the copy style already used in account.html."""
    if value is None:
        return None
    return value.strftime("%b %-d, %Y")  # on Windows, use %#d instead of %-d


def _format_bytes(n: int) -> str:
    """1288490188 -> '1.2 GB'. Good enough for display; not locale-aware."""
    gb = n / 1024**3
    if gb >= 0.1:
        return f"{gb:.1f} GB"
    mb = n / 1024**2
    return f"{mb:.0f} MB"


@account_router.get("/account", response_class=HTMLResponse)
async def handle_get_account_details(
    request: Request,
    user: Annotated[User, Depends(current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    now = datetime.now(UTC)
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

    subscription = user.subscription

    sub_id = None
    current_plan = "none"
    subscription_status = "inactive"
    renews_at = None
    resumes_at = None
    trial_days_left = None
    portal_links = {}
    storage_used_bytes = 0
    cancel_at = None
    can_undo_cancel = False

    # No subscription row at all. This shouldn't normally happen if a trial
    # row is created at signup, but the account page should still render in
    # a "no plan yet" state rather than 400 — the billing section already
    # knows how to show purchase CTAs for this.
    if not subscription:
        return temp.TemplateResponse(
            request,
            "index.html",
        )
    else:
        current_plan = PRICE_ID_TO_PLAN.get(str(subscription.price_id), "none")
        subscription_status = subscription.status
        sub_id = subscription.subscription_id

        renews_at = _format_date(subscription.current_period_end)

        # Not tracked in the schema yet — Paddle exposes the scheduled
        # resume date on the subscription entity (scheduled_change.resume_at)
        # when status is paused. Either store it on a webhook-driven column,
        # or fetch it live from Paddle here if you need it on this page.
        resumes_at = None
        cancel_at = (
            _format_date(subscription.cancel_at) if subscription.cancel_at else None
        )
        can_undo_cancel = (
            subscription.status == SubscriptionStatus.ACTIVE.value
            and subscription.cancel_at is not None
            and subscription.cancel_at > now
        )

        trial_days_left = None
        if subscription_status == "trial" and subscription.trial_end:
            trial_days_left = max((subscription.trial_end - now).days, 0)

    portal_links = {}
    if subscription.paddle_customer_id and subscription.subscription_id:
        portal_links = await get_customer_portal_links(
            subscription.paddle_customer_id, subscription.subscription_id
        )

    # --- Usage: submissions (existing quota logic, now driven by the plan
    #     the user is actually on instead of a nonexistent user.submission_quota)
    quota_limit = PLAN_SUBMISSION_QUOTAS.get(current_plan, DEFAULT_TRIAL_QUOTA)

    quota_usage = (
        await db.scalar(
            select(func.count(Submission.id))
            .select_from(Submission)
            .join(FormDB, Submission.form_id == FormDB.id)
            .join(Project, FormDB.project_id == Project.id)
            .where(Project.user_id == user.id)
            .where(Submission.created_at >= month_start)
        )
        or 0
    )
    quota_percentage = (
        min(int((quota_usage / quota_limit) * 100), 100) if quota_limit > 0 else 100
    )

    # --- Usage: storage. Solo has no storage allowance at all (no file
    #     uploads on that tier), so there's nothing meaningful to show there.
    storage_limit_bytes = PLAN_STORAGE_LIMITS_BYTES.get(current_plan, 0)
    storage_used_bytes = subscription.storage_bytes_used if subscription else 0
    storage_percentage = (
        min(int((storage_used_bytes / storage_limit_bytes) * 100), 100)
        if storage_limit_bytes > 0
        else 0
    )

    return temp.TemplateResponse(
        request,
        "account.html",
        {
            "user": user,
            "page": "account",
            # Billing / subscription
            "sub_id": sub_id,
            "current_plan": current_plan,
            "subscription_status": subscription_status,
            "renews_at": renews_at,
            "resumes_at": resumes_at,
            "trial_days_left": trial_days_left,
            "paddle_client_token": settings.PADDLE_CLIENT_TOKEN,
            "paddle_environment": settings.PADDLE_ENVIRONMENT,
            "paddle_solo_price": settings.PADDLE_PRICE_ID_SOLO,
            "paddle_studio_price": settings.PADDLE_PRICE_ID_STUDIO,
            "paddle_links": portal_links,
            "cancel_at": cancel_at,  # date cancellation takes effect
            "can_undo_cancel": can_undo_cancel,  # show/hide undo button in template
            # Usage
            "quota_usage": quota_usage,
            "quota_limit": quota_limit,
            "quota_percentage": quota_percentage,
            "storage_used_bytes": storage_used_bytes,
            "storage_limit_bytes": storage_limit_bytes,
            "storage_percentage": storage_percentage,
            "storage_used_display": _format_bytes(storage_used_bytes),
            "storage_limit_display": _format_bytes(storage_limit_bytes)
            if storage_limit_bytes
            else None,
        },
    )
