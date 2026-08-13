import hashlib
import hmac
from typing import Annotated

import httpx
from fastapi import APIRouter, Depends, Header, HTTPException, Request
from fastapi.responses import JSONResponse
from loguru import logger as log
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.core.settings import settings
from app.models.user import ProcessedWebhook, Subscription, User
from app.services.dependencies import current_user
from app.services.subscription import handle_paddle_webhook

user_router = APIRouter()

headers = {
    "Authorization": f"Bearer {settings.PADDLE_API_KEY}",
    "Content-Type": "application/json",
    "Accept": "application/json",
}


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
    SUBSCRIPTION_ID = subscription.subscription_id
    url = f"{settings.PADDLE_BASE_URL}/subscriptions/{SUBSCRIPTION_ID}/pause"

    headers = {
        "Authorization": f"Bearer {settings.PADDLE_API_KEY}",
        "Content-Type": "application/json",
    }
    payload = {
        "effective_from": "next_billing_period"  # or "immediately"
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

    SUBSCRIPTION_ID = subscription.subscription_id
    url = f"{settings.BASE_URL}/subscriptions/{SUBSCRIPTION_ID}/resume"
    headers = {
        "Authorization": f"Bearer {settings.PADDLE_API_KEY}",
        "Content-Type": "application/json",
    }
    payload = {
        "effective_from": "next_billing_period"  # or "immediately"
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

    return {"message": "Subscription paused successfully"}
