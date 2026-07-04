from datetime import datetime, timezone
from typing import Optional
from fastapi import status as FastApiStatus
from fastapi import HTTPException
import httpx
from loguru import logger as log
from pydantic import BaseModel, ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.settings import settings
from app.models.user import Subscription, User
from app.schemas.user import SubscriptionStatus

headers = {
    "Authorization": f"Bearer {str(settings.PADDLE_API_KEY)}",
    "Accept": "application/json",
}


class PaddleCustomerDetails(BaseModel):
    email: Optional[str] = None


class PaddleCustomerResponse(BaseModel):
    data: Optional[PaddleCustomerDetails] = None


# =========================================================
# HELPERS
# =========================================================


async def get_customer_email(customer_id: str) -> str | None:
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{settings.PADDLE_BASE_URL}/customers/{customer_id}", headers=headers
            )
            # https own module to check for response status and throw error
            response.raise_for_status()

            payload = PaddleCustomerResponse.model_validate(response.json())
            if payload.data:
                return payload.data.email
            return None

    except httpx.HTTPStatusError as e:
        log.error(f"❌ Paddle API error ({e.response.status_code}): {e.response.text}")
        return None
    except httpx.RequestError as e:
        log.error(f"❌ Paddle network/timeout error: {e}")
        return None
    except ValidationError as e:
        log.error(f"❌ Paddle data validation failed: {e.json()}")
        return None
    except Exception as e:
        log.error(f"❌ Unexpected error fetching Paddle customer: {e}")
        return None


async def get_user_by_id(user_id: str, db: AsyncSession):
    try:
        query_result = await db.execute(select(User).where(User.id == user_id))
        return query_result.scalar_one_or_none()
    except Exception as e:
        log.error(f"Error finding user by user_id {user_id}: {e} ")
        return None


async def get_subscription_by_user_id(user_id: str, db: AsyncSession):

    try:
        query_result = await db.execute(
            select(Subscription).where(Subscription.user_id == user_id)
        )
        return query_result.scalar_one_or_none()
    except Exception as e:
        log.error(f"Error finding Subscription by user id {user_id}: {e} ")
        return None


def extract_subscription_data(payload: dict):
    subscription_id = payload.get("id")
    items = payload.get("items") or []
    status = payload.get("status")
    customer_id = payload.get("customer_id")
    user_id = payload.get("custom_data", {}).get("user_id")
    first_item = items[0] if items else {}
    price_id = first_item.get("price", {}).get("id")

    billing_cycle = payload.get("billling_cycle") or {}
    interval = billing_cycle.get("interval")
    current_billing_period = payload.get("current_billing_period") or {}
    scheduled_change = payload.get("scheduled_change", {})
    cancel_at_raw = None

    if scheduled_change and isinstance(scheduled_change, dict):
        cancel_at_raw = scheduled_change.get("effective_at")

    def parse_dt(value):
        if not value:
            return None
        if isinstance(value, datetime):
            return value
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except Exception:
            return None

    return {
        "subscription_id": subscription_id,
        "customer_id": customer_id,
        "user_id": user_id,
        "status": status,
        "price_id": price_id,
        "plan_interval": interval,
        "current_period_start": parse_dt(current_billing_period.get("starts_at")),
        "current_period_end": parse_dt(current_billing_period.get("ends_at")),
        "cancel_at": parse_dt(cancel_at_raw) if cancel_at_raw else None,
        "canceled_at": parse_dt(payload.get("canceled_at")),
    }


# =========================================================
# EVENT HANDLERS
# =========================================================


async def handle_subscription_activated(payload: dict, db: AsyncSession):

    # Extract values from the incoming Paddle payload
    data = extract_subscription_data(payload)
    subscription_id = data.get("subscription_id")
    customer_id = data.get("customer_id")
    user_id = data.get("user_id")
    status = data.get("status")
    price_id = data.get("price_id")
    plan_interval = data.get("plan_interval")
    current_period_start = data.get("current_period_start")
    current_period_end = data.get("current_period_end")
    cancel_at = data.get("cancel_at")
    canceled_at = data.get("canceled_at")
    try:
        if not customer_id:
            log.warning(
                f"subscription.created missing customer_id: subscription_id={subscription_id}"
            )
            return None

        # Resolve user via Id
        if not user_id or not isinstance(user_id, str):
            log.error(
                f"Cannot process webhook. user_id is missing or invalid type in custom_data for sub: {subscription_id}"
            )
            return None
        user = await get_user_by_id(user_id, db)
        if not user:
            log.warning(
                f"No user found for Paddle customer {customer_id} (subscription {subscription_id})"
            )
            raise HTTPException(
                status_code=FastApiStatus.HTTP_400_BAD_REQUEST,
                detail=f"No user found for Paddle customer {customer_id} (subscription {subscription_id})",
            )
        query = select(Subscription).where(
            Subscription.subscription_id == subscription_id
        )
        result = await db.execute(query)
        subscription = result.scalar_one_or_none()

        if not subscription:
            # Find existing subscription for user
            subscription = await get_subscription_by_user_id(user.id, db)

        # Map Paddle status string to SubscriptionStatus enum
        def _map_status(s: str | None) -> SubscriptionStatus:
            if not s:
                return SubscriptionStatus.TRIAL
            s = s.lower()
            if s in ("trial", "trialing"):
                return SubscriptionStatus.TRIAL
            if s in ("active", "activated"):
                return SubscriptionStatus.ACTIVE
            if s in ("canceled", "cancelled", "cancelled_by_customer"):
                return SubscriptionStatus.CANCELED
            return SubscriptionStatus.TRIAL

        status_enum = _map_status(status)

        now = datetime.now(timezone.utc)

        if subscription:
            # Update existing subscription
            subscription.subscription_id = (
                subscription_id or subscription.subscription_id
            )
            subscription.paddle_customer_id = (
                customer_id or subscription.paddle_customer_id
            )
            subscription.status = status_enum.value
            subscription.price_id = price_id or subscription.price_id
            subscription.plan_interval = plan_interval or subscription.plan_interval
            subscription.current_period_start = (
                current_period_start or subscription.current_period_start
            )
            subscription.current_period_end = (
                current_period_end or subscription.current_period_end
            )
            subscription.cancel_at = cancel_at or subscription.cancel_at
            subscription.canceled_at = canceled_at or subscription.canceled_at
            subscription.updated_at = now

            try:
                await db.commit()
                await db.refresh(subscription)
            except Exception:
                await db.rollback()
                log.exception("Failed to commit updated subscription")
                return None

            log.info(
                f"Updated subscription for user={user.email} subscription_id={subscription.subscription_id}"
            )
            return subscription

        # Create a new subscription row
        new_sub = Subscription(
            user_id=user.id,
            subscription_id=subscription_id,
            paddle_customer_id=customer_id,
            status=status_enum.value,
            price_id=price_id,
            plan_interval=plan_interval,
            current_period_start=current_period_start,
            current_period_end=current_period_end,
            cancel_at=cancel_at,
            canceled_at=canceled_at,
            created_at=now,
            updated_at=now,
        )

        try:
            db.add(new_sub)
            await db.commit()
            await db.refresh(new_sub)
        except Exception:
            await db.rollback()
            log.exception("Failed to create subscription")
            return None

        log.info(
            f"Created subscription for user={user.email} subscription_id={new_sub.subscription_id}"
        )
        return new_sub

    except Exception as e:
        try:
            await db.rollback()
        except Exception:
            pass
        log.exception(f"Unhandled error in handle_subscription_created: {e}")
        return None


async def handle_subscription_updated(
    payload: dict,
    db: AsyncSession,
):
    data = extract_subscription_data(payload)

    subscription_id = data.get("subscription_id")
    customer_id = data.get("customer_id")
    user_id = data.get("user_id")
    status = data.get("status")
    price_id = data.get("price_id")
    plan_interval = data.get("plan_interval")
    current_period_start = data.get("current_period_start")
    current_period_end = data.get("current_period_end")
    cancel_at = data.get("cancel_at")
    canceled_at = data.get("canceled_at")

    try:
        if not customer_id and not subscription_id:
            log.warning("subscription.updated missing identifiers")
            return None

        user = None

        if not user_id or not isinstance(user_id, str):
            log.error(
                f"Cannot process webhook. user_id is missing or invalid type in custom_data for sub: {subscription_id}"
            )
            return None
        user = await get_user_by_id(user_id, db)

        subscription = None

        if user:
            subscription = await get_subscription_by_user_id(
                user.id,
                db,
            )

        if not subscription and subscription_id:
            result = await db.execute(
                select(Subscription).where(
                    Subscription.subscription_id == subscription_id
                )
            )

            subscription = result.scalar_one_or_none()

        def map_status(
            paddle_status: str | None,
        ) -> SubscriptionStatus:

            if not paddle_status:
                return SubscriptionStatus.TRIAL

            paddle_status = paddle_status.lower()

            if paddle_status in (
                "trial",
                "trialing",
            ):
                return SubscriptionStatus.TRIAL

            if paddle_status in (
                "active",
                "activated",
            ):
                return SubscriptionStatus.ACTIVE

            if paddle_status in (
                "canceled",
                "cancelled",
            ):
                return SubscriptionStatus.CANCELED

            # if paddle_status == "past_due":
            #     return SubscriptionStatus.PAST_DUE

            return SubscriptionStatus.TRIAL

        status_enum = map_status(status)

        now = datetime.now(timezone.utc)

        if not subscription:
            new_subscription = Subscription(
                user_id=user.id if user else None,
                subscription_id=subscription_id,
                paddle_customer_id=customer_id,
                status=status_enum.value,
                price_id=price_id,
                plan_interval=plan_interval,
                current_period_start=current_period_start,
                current_period_end=current_period_end,
                cancel_at=cancel_at,
                canceled_at=canceled_at,
                created_at=now,
                updated_at=now,
            )

            db.add(new_subscription)

            try:
                await db.commit()
                await db.refresh(new_subscription)
            except Exception:
                await db.rollback()
                log.exception("Failed creating subscription during update event")
                return None

            return new_subscription

        subscription.status = status_enum.value
        subscription.price_id = price_id or subscription.price_id
        subscription.plan_interval = plan_interval or subscription.plan_interval
        subscription.current_period_start = (
            current_period_start or subscription.current_period_start
        )
        subscription.current_period_end = (
            current_period_end or subscription.current_period_end
        )
        subscription.cancel_at = cancel_at
        subscription.canceled_at = canceled_at
        subscription.updated_at = now

        try:
            await db.commit()
            await db.refresh(subscription)
        except Exception:
            await db.rollback()

            log.exception("Failed committing subscription.updated")

            return None

        log.info(f"Updated subscription {subscription.subscription_id}")

        return subscription

    except Exception as e:
        try:
            await db.rollback()
        except Exception:
            pass

        log.exception(f"Unhandled error in handle_subscription_updated: {e}")

        return None


async def handle_subscription_canceled(
    payload: dict,
    db: AsyncSession,
):
    data = extract_subscription_data(payload)
    user_id = data.get("user_id")
    subscription_id = data.get("subscription_id")
    customer_id = data.get("customer_id")
    # current_period_end = data.get("current_period_end")
    cancel_at = data.get("cancel_at")

    try:
        if not customer_id and not subscription_id:
            log.warning("subscription.canceled missing identifiers")
            return None

        user = None

        if not user_id or not isinstance(user_id, str):
            log.error(
                f"Cannot process webhook. user_id is missing or invalid type in custom_data for sub: {subscription_id}"
            )
            return None
        user = await get_user_by_id(user_id, db)

        subscription = None

        if user:
            subscription = await get_subscription_by_user_id(
                user.id,
                db,
            )

        if not subscription and subscription_id:
            result = await db.execute(
                select(Subscription).where(
                    Subscription.subscription_id == subscription_id
                )
            )

            subscription = result.scalar_one_or_none()

        if not subscription:
            log.warning(f"Subscription not found (subscription_id={subscription_id})")
            return None

        now = datetime.now(timezone.utc)

        subscription.status = SubscriptionStatus.CANCELED.value

        # Access remains valid until period end
        subscription.cancel_at = cancel_at or now

        subscription.canceled_at = cancel_at or now
        subscription.updated_at = now

        try:
            await db.commit()
            await db.refresh(subscription)
        except Exception:
            await db.rollback()

            log.exception("Failed committing subscription.canceled")
            return None

        log.info(f"Subscription canceled {subscription.subscription_id}")

        return subscription

    except Exception as e:
        try:
            await db.rollback()
        except Exception:
            pass

        log.exception(f"Unhandled error in handle_subscription_canceled: {e}")

        return None


async def handle_payment_failed(
    payload: dict,
    db: AsyncSession,
):
    subscription_data = payload.get("data", {})

    subscription_id = subscription_data.get("subscription_id")

    try:
        if not subscription_id:
            log.warning("payment_failed missing subscription_id")
            return None

        result = await db.execute(
            select(Subscription).where(Subscription.subscription_id == subscription_id)
        )

        subscription = result.scalars().first()

        if not subscription:
            log.warning(f"No subscription found for payment failure {subscription_id}")
            return None

        subscription.updated_at = datetime.now(timezone.utc)

        try:
            await db.commit()
        except Exception:
            await db.rollback()

            log.exception("Failed committing payment_failed event")

            return None

        log.warning(f"Payment failed for subscription {subscription.subscription_id}")

        return subscription

    except Exception as e:
        try:
            await db.rollback()
        except Exception:
            pass

        log.exception(f"Unhandled error in handle_payment_failed: {e}")

        return None


# =========================================================
# MAIN WEBHOOK ROUTER
# =========================================================


async def handle_paddle_webhook(
    event_type: str,
    payload: dict,
    db: AsyncSession,
):
    try:
        match event_type:
            case "subscription.created" | "subscription.activated":
                return await handle_subscription_activated(
                    payload,
                    db,
                )

            case (
                "subscription.updated" | "subscription.resumed" | "subscription.paused"
            ):
                return await handle_subscription_updated(
                    payload,
                    db,
                )

            case "subscription.canceled":
                return await handle_subscription_canceled(
                    payload,
                    db,
                )

            case "subscription.past_due":
                return await handle_payment_failed(
                    payload,
                    db,
                )

            case "transaction.payment_failed":
                return await handle_payment_failed(
                    payload,
                    db,
                )

            case _:
                log.warning(f"Unhandled Paddle webhook: {event_type}")
                return None

    except Exception as e:
        try:
            await db.rollback()
        except Exception:
            pass

        log.exception(f"Paddle webhook failed for event={event_type}: {e}")

        raise
