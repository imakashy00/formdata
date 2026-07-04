from typing import Annotated

from fastapi import APIRouter, Depends, Header, Request, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from pydantic import BaseModel
import hashlib
import httpx
import hmac


from app.services.subscription import handle_paddle_webhook
from app.schemas.user import DBUser, SubscriptionStatus
from app.services.dependencies import current_user
from app.models.user import Subscription
from app.core.templates import temp
from app.core.db import get_db
from app.core.settings import settings

user_router = APIRouter()

headers = {
    "Authorization": f"Bearer {settings.PADDLE_API_KEY}",
    "Content-Type": "application/json",
    "Accept": "application/json",
}


@user_router.get("/modal", response_class=HTMLResponse)
async def subscription_modal(
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: DBUser = Depends(current_user),
):
    result = await db.execute(
        select(Subscription).filter(Subscription.user_id == user.id)
    )
    subs = result.scalars().first()
    is_active = bool(subs and subs.status == SubscriptionStatus.ACTIVE)
    template = (
        "components/manage_modal.html" if is_active else "components/pricing_modal.html"
    )
    return temp.TemplateResponse(
        request,
        template,
        {
            "request": request,
            "email": user.email,
            "user_id": user.id,
            # pricing values only used by pricing modal
            "monthly_price_id": settings.PADDLE_MONTHLY_PRICE_ID,
            "yearly_price_id": settings.PADDLE_YEARLY_PRICE_ID,
            "monthly_amount": 1900,
            "yearly_amount": 19900,
            "currency": "USD",
            "features": [
                "Unlimited AI-generated notes",
                "Folder organization",
                "Rich-text editor",
                "AI chatbot",
                "Priority support & PDF export",
            ],
            # manage modal extras
            "current_period_end": getattr(subs, "current_period_end", None),
        },
    )


class CancelReason(BaseModel):
    reason: str


@user_router.post("/subscription/cancel")
async def cancel_subscription_req(
    reason: CancelReason,
    db: AsyncSession = Depends(get_db),
    user: DBUser = Depends(current_user),
):
    if not settings.PADDLE_API_KEY:
        raise HTTPException(status_code=500, detail="Paddle API key not configured")

    result = await db.execute(
        select(Subscription).filter(Subscription.user_id == user.id)
    )
    subs = result.scalars().first()
    if not subs or not subs.subscription_id:
        raise HTTPException(status_code=404, detail="Active subscription not found")
    if subs.status == SubscriptionStatus.CANCELED:
        raise HTTPException(
            status_code=400,
            detail="Subscription already canceled",
        )

    url = f"{settings.PADDLE_BASE_URL}/subscriptions/{subs.subscription_id}/cancel"

    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(url, headers=headers)

        if response.status_code not in [200, 201]:
            # log.error( f"Paddle cancel failed: " f"{response.status_code} " f"{response.text}" )
            raise HTTPException(
                status_code=response.status_code,
                detail="Failed to cancel subscription",
            )
        else:
            return JSONResponse(
                status_code=200,
                content={
                    "success": True,
                    "message": (
                        "Subscription cancellation scheduled "
                        "for the end of the billing period."
                    ),
                },
            )

    except Exception as e:
        print(f"❌ Error canceling subscription: {e}")
        raise HTTPException(
            status_code=500, detail="Error requesting cancellation from Paddle"
        )


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
    request:Request,
    db: AsyncSession = Depends(get_db),
    paddle_signature: Annotated[str | None, Header()] = None,
):
    if not settings.PADDLE_WEBHOOK_SECRET:
        raise HTTPException(status_code=500, detail="Webhook secret not configured")
    if not paddle_signature:
        raise HTTPException(status_code=401, detail="Missing signature header")
    raw_body = await request.body()
    if not verify_signature(paddle_signature, raw_body):
        raise HTTPException(status_code=401, detail="Invalid signature")

    try:
        webhook_data = Webhook.model_validate_json(raw_body)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Invalid payload schema: {e}")
    await handle_paddle_webhook(webhook_data.event_type, webhook_data.data, db)
    return JSONResponse({"ok": True}, status_code=200)
