import hashlib
import hmac
from datetime import UTC, datetime
from typing import Annotated, Literal

import httpx
from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response
from fastapi.responses import JSONResponse
from loguru import logger as log
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.core.htmx import hx_toast_headers
from app.core.settings import settings
from app.models.user import ProcessedWebhook, Subscription, User
from app.schemas.user import SubscriptionStatus
from app.services.dependencies import current_user
from app.services.subscription import handle_paddle_webhook

user_router = APIRouter()

headers = {
    "Authorization": f"Bearer {settings.PADDLE_API_KEY}",
    "Content-Type": "application/json",
    "Accept": "application/json",
}

PLAN_PRICE_IDS: dict[str, str] = {
    "solo": settings.PADDLE_PRICE_ID_SOLO,
    "studio": settings.PADDLE_PRICE_ID_STUDIO,
}
PLAN_ORDER: dict[str, int] = {"trial": 0, "solo": 1, "studio": 2}


class ChangePlanPreviewResponse(BaseModel):
    plan: str
    action: Literal["charge", "credit"]
    amount_display: str
    currency_code: str


CURRENCY_SYMBOLS = {"USD": "$", "GBP": "£", "EUR": "€"}


class ChangePlanRequest(BaseModel):
    plan: Literal["solo", "studio"]


class Webhook(BaseModel):
    event_id: str
    event_type: str
    occurred_at: str
    notification_id: str
    data: dict


def verify_signature(sig_header: str, raw_body: bytes) -> bool:
    try:
        # 1. Parse header safely
        parts = dict(item.split("=") for item in sig_header.split(";"))
        timestamp = parts.get("ts")
        paddle_signature = parts.get("h1")

        if not timestamp or not paddle_signature:
            return False

        # 2. Reconstruct the payload exactly using raw bytes
        # Paddle expects: timestamp + ":" + raw_request_body_bytes
        payload = timestamp.encode("utf-8") + b":" + raw_body
        secret_key = settings.PADDLE_WEBHOOK_SECRET.encode("utf-8")
        # 3. Compute and securely compare hashes
        our_signature = hmac.new(
            secret_key, msg=payload, digestmod=hashlib.sha256
        ).hexdigest()
        return hmac.compare_digest(paddle_signature, our_signature)

    except Exception:
        return False


@user_router.post("/webhook/paddle")
@user_router.post("/subscription/webhook")
async def process_webhook(
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
    paddle_signature: Annotated[str | None, Header()] = None,
):
    if not settings.PADDLE_WEBHOOK_SECRET:
        raise HTTPException(status_code=500, detail="Webhook secret not configured")
    if not paddle_signature:
        raise HTTPException(status_code=401, detail="Missing signature header")
    raw_body = await request.body()
    if not verify_signature(paddle_signature, raw_body):
        raise HTTPException(status_code=401, detail="Invalid signature")

    webhook_data = Webhook.model_validate_json(raw_body)
    try:
        query = select(ProcessedWebhook).where(
            ProcessedWebhook.event_id == webhook_data.event_id
        )
        result = await db.execute(query)
        already_processed = result.scalar_one_or_none()
        if already_processed:
            log.info(
                f"Duplicate webhook detected. Event {webhook_data.event_id} already processed. Skipping."
            )
            return {"status": "skipped", "message": "Duplicate event"}
        new_guard = ProcessedWebhook(
            event_id=webhook_data.event_id, event_type=webhook_data.event_type
        )
        db.add(new_guard)
        await handle_paddle_webhook(webhook_data.event_type, webhook_data.data, db)
        await db.commit()
        return JSONResponse({"ok": True}, status_code=200)
    except Exception as e:
        await db.rollback()
        log.exception(f"Webhook processing crashed for event {webhook_data.event_id}")
        raise HTTPException(status_code=400, detail=f"Invalid payload schema: {e}")


@user_router.post("/billing/pause")
async def handle_billing_pause(
    request: Request,
    user: Annotated[User, Depends(current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    sub_query = select(Subscription).where(Subscription.user_id == user.id)
    query_result = await db.execute(sub_query)
    subscription = query_result.scalar_one_or_none()
    if not subscription:
        raise HTTPException(404, "Subscription not found")
    if subscription.status != SubscriptionStatus.ACTIVE.value:
        raise HTTPException(400, "Only an active subscription can be paused")
    now = datetime.now(UTC)
    if subscription.cancel_at and subscription.cancel_at > now:
        raise HTTPException(
            400,
            "This subscription has a cancellation scheduled — undo the "
            "cancellation before pausing",
        )
    SUBSCRIPTION_ID = subscription.subscription_id
    url = f"{settings.PADDLE_BASE_URL}/subscriptions/{SUBSCRIPTION_ID}/pause"

    headers = {
        "Authorization": f"Bearer {settings.PADDLE_API_KEY}",
        "Content-Type": "application/json",
    }
    payload = {
        "effective_from": "immediately"  # "next_billing_period"
    }
    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(url, headers=headers, json=payload)

            # Raise an exception for HTTP errors (4xx or 5xx)
            response.raise_for_status()
    except httpx.HTTPStatusError as e:
        log.error(
            f"Paddle returned an error pausing subscription for user {user.id}: {e.response.text}"
        )
        raise HTTPException(
            status_code=502, detail="Failed to pause subscription with Paddle"
        )
    except Exception as e:
        log.error(f"Unexpected error pausing subscription for user {user.id}: {e}")
        raise HTTPException(status_code=500, detail="Unexpected error")

    subscription.status = SubscriptionStatus.PAUSED.value
    await db.commit()

    return {"message": "Subscription paused successfully"}


@user_router.post("/billing/resume")
async def handle_billing_resume(
    request: Request,
    user: Annotated[User, Depends(current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    sub_query = select(Subscription).where(Subscription.user_id == user.id)
    query_result = await db.execute(sub_query)
    subscription = query_result.scalar_one_or_none()
    if not subscription:
        raise HTTPException(404, "Subscription not found")
    if subscription.status != SubscriptionStatus.PAUSED.value:
        raise HTTPException(400, "Only a paused subscription can be resumed")

    SUBSCRIPTION_ID = subscription.subscription_id
    url = f"{settings.PADDLE_BASE_URL}/subscriptions/{SUBSCRIPTION_ID}/resume"
    headers = {
        "Authorization": f"Bearer {settings.PADDLE_API_KEY}",
        "Content-Type": "application/json",
    }
    payload = {
        "effective_from": "immediately",
        "on_resume": "continue_existing_billing_period",
    }

    async def _post(body: dict) -> httpx.Response:
        async with httpx.AsyncClient() as client:
            resp = await client.post(url, headers=headers, json=body)
            resp.raise_for_status()
            return resp

    try:
        await _post(payload)
    except httpx.HTTPStatusError as e:
        error_code = ""
        try:
            error_code = e.response.json().get("error", {}).get("code", "")
        except ValueError:
            pass

        if error_code == "subscription_continuing_existing_billing_period_not_allowed":
            payload["on_resume"] = "start_new_billing_period"
            try:
                await _post(payload)  # success here means resume worked — no re-raise
            except httpx.HTTPStatusError as retry_err:
                log.error(
                    f"Paddle returned an error resuming subscription for user {user.id}: {retry_err.response.text}"
                )
                raise HTTPException(502, "Failed to resume subscription with Paddle")
            except Exception as retry_err:
                log.error(
                    f"Unexpected error resuming subscription for user {user.id}: {retry_err}"
                )
                raise HTTPException(500, "Unexpected error")
        else:
            log.error(
                f"Paddle returned an error resuming subscription for user {user.id}: {e.response.text}"
            )
            raise HTTPException(502, "Failed to resume subscription with Paddle")

    except Exception as e:
        log.error(f"Unexpected error resuming subscription for user {user.id}: {e}")
        raise HTTPException(status_code=500, detail="Unexpected error")

    subscription.status = SubscriptionStatus.ACTIVE.value
    await db.commit()

    return {"message": "Subscription resumed successfully"}


@user_router.post("/billing/cancel/undo")
async def handle_undo_cancellation(
    request: Request,
    user: Annotated[User, Depends(current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    sub_query = select(Subscription).where(Subscription.user_id == user.id)
    query_result = await db.execute(sub_query)
    subscription = query_result.scalar_one_or_none()

    if not subscription:
        raise HTTPException(404, "Subscription not found")

    # Only allow undo if subscription is still active with a future cancel_at
    now = datetime.now(UTC)
    if subscription.status != SubscriptionStatus.ACTIVE.value:
        raise HTTPException(400, "Subscription is already canceled, cannot undo")

    if not subscription.cancel_at or subscription.cancel_at <= now:
        raise HTTPException(400, "No pending cancellation to undo")

    url = f"{settings.PADDLE_BASE_URL}/subscriptions/{subscription.subscription_id}"
    headers = {
        "Authorization": f"Bearer {settings.PADDLE_API_KEY}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    payload = {
        "scheduled_change": None  # removes the scheduled cancellation
    }

    try:
        async with httpx.AsyncClient() as client:
            response = await client.patch(url, headers=headers, json=payload)
            response.raise_for_status()

        # Clear cancel_at locally after successful undo
        subscription.cancel_at = None
        await db.commit()

    except httpx.HTTPStatusError as e:
        log.error(
            f"Paddle returned an error undoing cancellation for user {user.id}: {e.response.text}"
        )
        raise HTTPException(
            502,
            "Failed to undo cancellation with Paddle",
            headers=hx_toast_headers(
                "Couldn't undo the cancellation. Please try again.", "error"
            ),
        )
    except Exception as e:
        log.error(f"Unexpected error undoing cancellation for user {user.id}: {e}")
        raise HTTPException(
            500,
            "Unexpected error",
            headers=hx_toast_headers(
                "Something went wrong. Please try again.", "error"
            ),
        )
    return Response(
        status_code=200,
        headers=hx_toast_headers(
            "Cancellation removed — your plan will continue as normal.",
            "success",
            reload=True,
        ),
    )


def _plan_from_price_id(price_id: str | None) -> str:
    return next(
        (p.capitalize() for p, pid in PLAN_PRICE_IDS.items() if pid == price_id),
        str(SubscriptionStatus.TRIAL.value).capitalize(),
    )


def _format_money(amount_str: str, currency_code: str) -> str:
    """Paddle amounts are integer strings in the lowest denomination (cents)."""
    try:
        value = int(amount_str) / 100
    except (TypeError, ValueError):
        return f"{amount_str} {currency_code}"
    symbol = CURRENCY_SYMBOLS.get(currency_code, "")
    return f"{symbol}{value:,.2f}" if symbol else f"{value:,.2f} {currency_code}"


async def _get_subscription_or_404(user: User, db: AsyncSession) -> Subscription:
    sub_query = select(Subscription).where(Subscription.user_id == user.id)
    query_result = await db.execute(sub_query)
    subscription = query_result.scalar_one_or_none()
    if not subscription:
        raise HTTPException(404, "Subscription not found")
    return subscription


def _validate_plan_change(subscription: Subscription, new_plan: str) -> tuple[str, str]:
    """Shared guard for preview + apply. Returns (current_plan, new_price_id)."""
    if subscription.status != SubscriptionStatus.ACTIVE.value:
        raise HTTPException(400, "Only an active subscription can change plans")

    now = datetime.now(UTC)
    if subscription.cancel_at and subscription.cancel_at > now:
        raise HTTPException(
            400,
            "This subscription has a cancellation scheduled — undo the "
            "cancellation before changing plans",
        )

    current_plan = _plan_from_price_id(subscription.price_id)
    if new_plan == current_plan:
        raise HTTPException(400, f"Subscription is already on the {new_plan} plan")

    return current_plan, PLAN_PRICE_IDS[new_plan]


def _build_paddle_request(
    subscription: Subscription, new_price_id: str
) -> tuple[str, dict, dict]:
    url = f"{settings.PADDLE_BASE_URL}/subscriptions/{subscription.subscription_id}"
    headers = {
        "Authorization": f"Bearer {settings.PADDLE_API_KEY}",
        "Content-Type": "application/json",
    }
    body = {
        "items": [{"price_id": new_price_id, "quantity": 1}],
        "proration_billing_mode": "prorated_immediately",
    }
    return url, headers, body


@user_router.post("/billing/change-plan/preview")
async def handle_billing_change_plan_preview(
    payload: ChangePlanRequest,
    user: Annotated[User, Depends(current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ChangePlanPreviewResponse:
    subscription = await _get_subscription_or_404(user, db)
    _current_plan, new_price_id = _validate_plan_change(subscription, payload.plan)
    url, headers, body = _build_paddle_request(subscription, new_price_id)

    try:
        async with httpx.AsyncClient() as client:
            response = await client.patch(f"{url}/preview", headers=headers, json=body)
            response.raise_for_status()
    except httpx.HTTPStatusError as e:
        log.error(
            f"Paddle returned an error previewing plan change for user {user.id}: {e.response.text}"
        )
        raise HTTPException(502, "Failed to preview plan change with Paddle")
    except Exception as e:
        log.error(f"Unexpected error previewing plan change for user {user.id}: {e}")
        raise HTTPException(500, "Unexpected error")

    data = response.json().get("data", {})
    result = (data.get("update_summary") or {}).get("result") or {}
    action = result.get("action", "charge")
    amount = result.get("amount", "0")
    currency_code = result.get("currency_code", "USD")

    return ChangePlanPreviewResponse(
        plan=payload.plan,
        action=action,
        amount_display=_format_money(amount, currency_code),
        currency_code=currency_code,
    )


@user_router.post("/billing/change-plan")
async def handle_billing_change_plan(
    payload: ChangePlanRequest,
    user: Annotated[User, Depends(current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    subscription = await _get_subscription_or_404(user, db)
    current_plan, new_price_id = _validate_plan_change(subscription, payload.plan)
    url, headers, body = _build_paddle_request(subscription, new_price_id)

    try:
        async with httpx.AsyncClient() as client:
            response = await client.patch(url, headers=headers, json=body)
            response.raise_for_status()
    except httpx.HTTPStatusError as e:
        log.error(
            f"Paddle returned an error changing plan for user {user.id}: {e.response.text}"
        )
        raise HTTPException(502, "Failed to update plan with Paddle")
    except Exception as e:
        log.error(f"Unexpected error changing plan for user {user.id}: {e}")
        raise HTTPException(500, "Unexpected error")

    subscription.price_id = new_price_id
    await db.commit()

    direction = (
        "upgraded"
        if PLAN_ORDER[payload.plan] > PLAN_ORDER.get(current_plan, 0)
        else "downgraded"
    )
    return {"message": f"Subscription {direction} to {payload.plan}"}
