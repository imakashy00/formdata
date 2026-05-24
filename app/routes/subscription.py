from fastapi import APIRouter, Depends, Header, Request, HTTPException
from paddle_billing.Notifications import Secret, Verifier
from fastapi.responses import HTMLResponse, JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from pydantic import BaseModel
import requests
import json


from app.services.subscription import activate_subscription, cancel_subscription
from app.schemas.user import DBUser, SubscriptionStatus
from app.services.dependencies import current_user
from app.models.user import Subscription
from app.core.templates import temp
from app.core.db import get_db
from app.core.settings import settings

user_router = APIRouter()

headers = {
    "Authorization": f"Bearer {str(settings.PADDLE_API_KEY)}",
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
    return temp.TemplateResponse(request,
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

    url = f"{settings.PADDLE_BASE_URL}/subscriptions/{subs.subscription_id}/cancel"

    try:
        response = requests.post(
            url, headers=headers, json={"effective_from": "immediately"}
        )

        if response.status_code == 200:
            # ✅ Just log & acknowledge request
            # print(
            #     f"🟡 Paddle cancellation requested for subscription {subs.subscription_id}"
            # )
            # print(f"📝 Reason: {reason}")

            # return {
            #     "status": "pending",
            #     "message": "Cancellation request sent to Paddle",
            # }
            pass
        else:
            raise HTTPException(status_code=response.status_code, detail=response.text)

    except Exception as e:
        print(f"❌ Error canceling subscription: {e}")
        raise HTTPException(
            status_code=500, detail="Error requesting cancellation from Paddle"
        )


class PaddleRequestAdapter:
    def __init__(self, body: bytes, headers: dict[str, str]):
        self.body = body
        self.headers = headers


@user_router.post("/webhook/paddle")
async def manage_subs(
    request: Request,
    db: AsyncSession = Depends(get_db),
    paddle_signature: str = Header(
        None,
        alias="Paddle-Signature",
    ),
):
    if not settings.PADDLE_WEBHOOK_SECRET:
        raise HTTPException(status_code=500, detail="Webhook secret not configured")
    raw = await request.body()
    headers = dict(request.headers)
    if paddle_signature:
        headers["Paddle-Signature"] = paddle_signature
    pr = PaddleRequestAdapter(raw, headers)
    try:
        ok = Verifier().verify(pr, secrets=[Secret(settings.PADDLE_WEBHOOK_SECRET)])  # type: ignore
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Verification error: {e}")
    if not ok:
        raise HTTPException(status_code=400, detail="Invalid Paddle webhook signature")
    payload = json.loads(raw.decode("utf-8"))
    event_type = payload.get("event_type")
    try:
        match event_type:
            case "subscription.activated":
                await activate_subscription(payload, db)
            case "subscription.canceled":
                await cancel_subscription(payload, db)
                print("🛑 Subscription canceled")
            case _:
                print("do not know what to do")
    except Exception as e:
        return JSONResponse(status_code=500, content=f"Something went wrong {e}")
    return JSONResponse({"ok": True}, status_code=200)
