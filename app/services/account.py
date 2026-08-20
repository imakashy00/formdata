from datetime import UTC, datetime

import httpx
from fastapi import HTTPException
from loguru import logger as log
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.settings import settings
from app.models.user import Form as FormDB
from app.models.user import Project, Submission, Subscription
from app.routes.subscription import _plan_from_price_id
from app.schemas.user import SubscriptionStatus
from app.services.bill_calculation import PLAN_LIMITS


def _format_date(value: datetime | None) -> str | None:
    """'Aug 20, 2026' — matches the copy style already used in account.html."""
    if value is None:
        return None
    return value.strftime("%b %-d, %Y")  # on Windows, use %#d instead of %-d


def get_subscription_state(
    subscription: Subscription | None,
    now: datetime,
) -> dict:
    """Build the subscription-related state for the account page."""

    if not subscription:
        return {
            "current_plan": "none",
            "subscription_status": "inactive",
            "sub_id": None,
            "renews_at": None,
            "resumes_at": None,
            "trial_days_left": None,
            "cancel_at": None,
            "can_undo_cancel": False,
        }

    current_plan = _plan_from_price_id(subscription.price_id)

    cancel_at = _format_date(subscription.cancel_at) if subscription.cancel_at else None

    can_undo_cancel = (
        subscription.status == SubscriptionStatus.ACTIVE.value
        and subscription.cancel_at is not None
        and subscription.cancel_at > now
    )

    trial_days_left = None

    if subscription.status == "trial" and subscription.trial_end:
        trial_days_left = max(
            (subscription.trial_end - now).days,
            0,
        )

    return {
        "current_plan": current_plan,
        "subscription_status": subscription.status,
        "sub_id": subscription.subscription_id,
        "renews_at": _format_date(subscription.current_period_end),
        "resumes_at": None,
        "trial_days_left": trial_days_left,
        "cancel_at": cancel_at,
        "can_undo_cancel": can_undo_cancel,
    }


async def get_customer_portal_links(customer_id: str, subscription_id: str) -> dict:
    """
    Dynamically generates fresh, authenticated Paddle portal links.
    These contain temporary login tokens and must not be cached.
    """
    url = f"{settings.PADDLE_BASE_URL}/customers/{customer_id}/portal-sessions"
    headers = {
        "Authorization": f"Bearer {settings.PADDLE_API_KEY}",
        "Content-Type": "application/json",
    }
    payload = {"subscription_ids": [subscription_id]}

    try:
        # Using httpx async client context manager
        async with httpx.AsyncClient() as client:
            response = await client.post(url, headers=headers, json=payload)

            # Raise an exception for HTTP errors (4xx or 5xx)
            response.raise_for_status()

            data = response.json()["data"]

            # Extract the deep links safely
            return {
                "overview_url": data["urls"]["general"]["overview"],
                "cancel_url": data["urls"]["subscriptions"][0]["cancel_subscription"],
                "update_payment_url": data["urls"]["subscriptions"][0][
                    "update_subscription_payment_method"
                ],
            }
    except HTTPException as e:
        log.error(f"Error fetching customer payment management links{e}")
        return {
            "overview_url": "#",
            "cancel_url": "#",
            "update_payment_url": "#",
        }


async def get_subscription_portal_links(
    subscription: Subscription | None,
) -> dict:
    """Get Paddle customer portal links for a subscription."""

    if not subscription:
        return {}

    if not subscription.paddle_customer_id:
        return {}

    if not subscription.subscription_id:
        return {}

    return await get_customer_portal_links(
        subscription.paddle_customer_id,
        subscription.subscription_id,
    )


def get_plan_limits(subscription: Subscription | None) -> dict:
    """Return limits for the current subscription plan."""

    if not subscription:
        return {
            "submissions": 0,
            "storage_gb": 0,
        }

    return PLAN_LIMITS.get(
        subscription.price_id or "",
        {
            "submissions": 1000,
            "storage_gb": 0,
        },
    )


async def get_monthly_submission_usage(
    db: AsyncSession,
    user_id,
    month_start: datetime,
) -> int:
    """Return the number of submissions created this month."""

    usage = await db.scalar(
        select(func.count(Submission.id))
        .select_from(Submission)
        .join(
            FormDB,
            Submission.form_id == FormDB.id,
        )
        .join(
            Project,
            FormDB.project_id == Project.id,
        )
        .where(Project.user_id == user_id)
        .where(Submission.created_at >= month_start)
    )

    return usage or 0


def calculate_submission_quota(
    usage: int,
    limit: int,
) -> dict:
    """Calculate submission quota presentation values."""

    if limit > 0:
        percentage = min(
            int((usage / limit) * 100),
            100,
        )

        extra = max(
            0,
            usage - limit,
        )
    else:
        percentage = 100
        extra = 0

    return {
        "usage": usage,
        "limit": limit,
        "percentage": percentage,
        "extra": extra,
    }


def calculate_storage_quota(
    subscription: Subscription | None,
    plan_data: dict,
) -> dict:
    """Calculate storage usage and quota presentation values."""

    storage_limit_gb = plan_data.get("storage_gb", 0)

    storage_used_bytes = subscription.storage_bytes_used if subscription else 0
    storage_used_gb = storage_used_bytes / (1 << 30)

    if storage_limit_gb > 0:
        percentage = min(int((storage_used_gb / storage_limit_gb) * 100), 100)
        extra_gb = max(0.0, storage_used_gb - storage_limit_gb)
    else:
        percentage = 0
        extra_gb = 0.0

    return {
        "used_gb": storage_used_gb,
        "limit_gb": storage_limit_gb,
        "percentage": percentage,
        "extra_gb": extra_gb,
    }


async def get_account_billing_data(
    db: AsyncSession,
    user,
) -> dict:
    """Build all billing/quota data required by the account page."""

    now = datetime.now(UTC)

    month_start = now.replace(
        day=1,
        hour=0,
        minute=0,
        second=0,
        microsecond=0,
    )

    subscription = user.subscription

    subscription_data = get_subscription_state(
        subscription,
        now,
    )

    portal_links = await get_subscription_portal_links(
        subscription,
    )

    plan_data = get_plan_limits(subscription)

    submission_usage = await get_monthly_submission_usage(
        db,
        user.id,
        month_start,
    )

    submission_quota = calculate_submission_quota(
        submission_usage,
        plan_data["submissions"],
    )

    storage_quota = calculate_storage_quota(
        subscription,
        plan_data,
    )

    return {
        **subscription_data,
        "portal_links": portal_links,
        "submission_quota": submission_quota,
        "storage_quota": storage_quota,
    }
