from app.models.user import Subscription, User
from datetime import datetime, timezone
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from loguru import logger as log
import requests
from app.core.settings import settings

headers = {
    "Authorization": f"Bearer {settings.PADDLE_API_KEY}",
    "Accept": "application/json",
}


def get_customer_email(customer_id: str):
    try:
        response = requests.get(
            f"{settings.PADDLE_BASE_URL}/customers/{customer_id}", headers=headers
        )
        data = response.json()  # dict
        customer = data.get("data") or {}
        email = customer.get("email")
        return email
    except Exception as e:
        log.error(f"❌ Error from paddle: {e}")


async def activate_subscription(payload: dict, db: AsyncSession):
    sub = payload.get("data", {})
    subscription_id = sub.get("id")
    customer_id = sub.get("customer_id")
    status = sub.get("status")
    price_id = (sub.get("items") or [])[0].get("price").get("id")
    plan_inerval = sub.get("billing_cycle").get("interval")
    current_period_start = sub.get("current_billing_period").get("starts_at")
    current_period_end = sub.get("current_billing_period").get("ends_at")
    user_email = get_customer_email(customer_id=customer_id)
    if not user_email:
        raise ValueError("Customer email not found for Paddle customer_id")

    result = await db.execute(select(User).filter(User.email == user_email))
    user = result.scalars().first()
    if user is None:
        raise ValueError(f"User not found for email {user_email}")

    result = await db.execute(
        select(Subscription).filter(Subscription.user_id == user.id)
    )
    subs = result.scalars().first()
    if subs:
        subs.current_period_start = current_period_start
        subs.current_period_end = current_period_end
        subs.subscription_id = subscription_id
        subs.paddle_customer_id = customer_id
        subs.plan_interval = plan_inerval
        subs.price_id = price_id
        subs.status = status
        subs.updated_at = datetime.now(timezone.utc)
        subs.cancel_at = None
        subs.canceled_at = None
    else:
        log.info("❌Subscription row not found")
    try:
        await db.commit()
    except Exception as e:
        log.error(f"❌ Error{e}")


async def cancel_subscription(payload: dict, db: AsyncSession):
    sub = payload.get("data", {})
    customer_id = sub.get("customer_id")
    status = sub.get("status")
    user_email = get_customer_email(customer_id=customer_id)
    if not user_email:
        raise ValueError("Customer email not found for Paddle customer_id")

    result = await db.execute(select(User).filter(User.email == user_email))
    user = result.scalars().first()
    if user is None:
        raise ValueError(f"User not found for email {user_email}")

    result = await db.execute(
        select(Subscription).filter(Subscription.user_id == user.id)
    )
    subs = result.scalars().first()
    if subs:
        now = datetime.now(timezone.utc)
        subs.status = status
        subs.cancel_at = subs.current_period_end
        subs.canceled_at = now
        subs.updated_at = now
    try:
        await db.commit()
    except Exception as e:
        await db.rollback()
        log.error(f"❌ cancel commit error: {e}")
