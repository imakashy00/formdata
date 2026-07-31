from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from app.core.settings import settings
from app.models.user import Subscription, User
from app.schemas.user import SubscriptionStatus
from app.services.bill_calculation import bill_overage, calculate_overage
from fastapi import HTTPException
from fastapi import status as FastApiStatus
from loguru import logger as log
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

headers = {
    "Authorization": f"Bearer {settings.PADDLE_API_KEY!s}",
    "Accept": "application/json",
}


class SubscriptionNotFoundError(Exception):
    """Raised when a subscription does not exist."""



class InvalidWebhookPayloadError(Exception):
    """Raised when InvalidWebhookPayloadError occurs."""



SYNC_EVENTS = {
    "subscription.created",
    "subscription.activated",
    "subscription.updated",
    "subscription.paused",
    "subscription.resumed",
}

STATUS_MAP = {
    "trialing": SubscriptionStatus.TRIAL,
    "active": SubscriptionStatus.ACTIVE,
    "paused": SubscriptionStatus.PAUSED,
    "canceled": SubscriptionStatus.CANCELED,
    "past_due": SubscriptionStatus.PAST_DUE,
}


@dataclass(slots=True)
class SubscriptionContext:
    user: User
    subscription: Subscription | None
    status: SubscriptionStatus
    now: datetime


@dataclass(slots=True)
class PaymentFailedWebhook:
    subscription_id: str

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> "PaymentFailedWebhook":
        subscription_id = payload.get("id")

        if str(subscription_id).startswith("txn"):
            subscription_id = payload.get("subscription_id")

        if not subscription_id:
            raise InvalidWebhookPayloadError(
                "Missing subscription_id in payment_failed payload."
            )

        return cls(subscription_id=subscription_id)


@dataclass(slots=True, kw_only=True)
class SubscriptionWebhook:
    subscription_id: str | None
    customer_id: str | None
    user_id: str | None

    status: str | None
    price_id: str | None
    plan_interval: str | None

    current_period_start: datetime | None
    current_period_end: datetime | None
    cancel_at: datetime | None
    canceled_at: datetime | None

    @staticmethod
    def _parse_datetime(value: str | None) -> datetime | None:
        """Convert Paddle ISO8601 timestamps into datetime objects."""
        if not value:
            return None
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except (TypeError, ValueError):
            return None

    @classmethod
    def from_payload(
        cls,
        payload: dict[str, Any],
    ) -> "SubscriptionWebhook":

        items = payload.get("items") or []
        first_item = next(iter(items), {})

        custom_data = payload.get("custom_data") or {}
        billing_cycle = payload.get("billing_cycle") or {}
        billing_period = payload.get("current_billing_period") or {}
        scheduled_change = payload.get("scheduled_change") or {}

        return cls(
            subscription_id=payload.get("id"),
            customer_id=payload.get("customer_id"),
            user_id=custom_data.get("user_id"),
            status=payload.get("status"),
            price_id=first_item.get("price", {}).get("id"),
            plan_interval=billing_cycle.get("interval"),
            current_period_start=cls._parse_datetime(billing_period.get("starts_at")),
            current_period_end=cls._parse_datetime(billing_period.get("ends_at")),
            cancel_at=cls._parse_datetime(scheduled_change.get("effective_at")),
            canceled_at=cls._parse_datetime(payload.get("canceled_at")),
        )


# =========================================================
# HELPERS
# =========================================================


def map_status(status: str | None) -> SubscriptionStatus:
    if not status:
        return SubscriptionStatus.TRIAL
    return STATUS_MAP.get(status.lower(), SubscriptionStatus.TRIAL)


async def get_user_by_id(user_id: str, db: AsyncSession):
    try:
        query_result = await db.execute(select(User).where(User.id == user_id))
        return query_result.scalar_one_or_none()
    except Exception as e:
        log.error(f"Error finding user by user_id {user_id}: {e} ")
        return None


async def get_subscription_by_user_id(
    user_id: str, db: AsyncSession
) -> Subscription | None:

    try:
        query_result = await db.execute(
            select(Subscription).where(Subscription.user_id == user_id)
        )
        return query_result.scalar_one_or_none()
    except Exception as e:
        log.error(f"Error finding Subscription by user id {user_id}: {e} ")
        return None


async def resolve_subscription_context(
    data: SubscriptionWebhook,
    db: AsyncSession,
) -> SubscriptionContext:
    if not data.customer_id:
        raise ValueError("Missing customer_id")

    if not data.user_id:
        raise ValueError("Missing user_id")

    user = await get_user_by_id(data.user_id, db)
    if not user:
        raise HTTPException(
            status_code=FastApiStatus.HTTP_400_BAD_REQUEST,
            detail=f"No user found for Paddle customer {data.customer_id}",
        )

    subscription = None

    if data.subscription_id:
        result = await db.execute(
            select(Subscription).where(
                Subscription.subscription_id == data.subscription_id
            )
        )
        subscription = result.scalar_one_or_none()

    if subscription is None:
        subscription = await get_subscription_by_user_id(user.id, db)

    return SubscriptionContext(
        user=user,
        subscription=subscription,
        status=map_status(data.status),
        now=datetime.now(UTC),
    )


def create_subscription(
    ctx: SubscriptionContext,
    data: SubscriptionWebhook,
    db: AsyncSession,
) -> Subscription:
    subscription = Subscription(
        user_id=ctx.user.id,
        subscription_id=data.subscription_id,
        paddle_customer_id=data.customer_id,
        status=ctx.status.value,
        price_id=data.price_id,
        plan_interval=data.plan_interval,
        current_period_start=data.current_period_start,
        current_period_end=data.current_period_end,
        cancel_at=data.cancel_at,
        canceled_at=data.canceled_at,
        created_at=ctx.now,
        updated_at=ctx.now,
    )

    db.add(subscription)

    return subscription


def update_subscription(
    subscription: Subscription,
    ctx: SubscriptionContext,
    data: SubscriptionWebhook,
) -> Subscription:
    subscription.subscription_id = data.subscription_id or subscription.subscription_id
    subscription.paddle_customer_id = (
        data.customer_id or subscription.paddle_customer_id
    )

    subscription.status = ctx.status.value

    subscription.price_id = data.price_id or subscription.price_id
    subscription.plan_interval = data.plan_interval or subscription.plan_interval

    subscription.current_period_start = (
        data.current_period_start or subscription.current_period_start
    )

    subscription.current_period_end = (
        data.current_period_end or subscription.current_period_end
    )

    subscription.cancel_at = data.cancel_at
    subscription.canceled_at = data.canceled_at
    subscription.updated_at = ctx.now

    return subscription


def cancel_subscription(
    subscription: Subscription,
    ctx: SubscriptionContext,
    data: SubscriptionWebhook,
) -> Subscription:
    subscription.status = SubscriptionStatus.CANCELED.value
    subscription.cancel_at = data.cancel_at
    subscription.canceled_at = data.cancel_at
    subscription.updated_at = ctx.now

    return subscription


async def save(
    db: AsyncSession,
    obj,
):
    try:
        await db.commit()
        await db.refresh(obj)
    except Exception as e:
        await db.rollback()
        log.exception(f"Failed to commit the transaction error:{e}")
        raise


def _period_rolled_over(subscription: Subscription, data: SubscriptionWebhook) -> bool:
    return bool(
        subscription.current_period_start
        and data.current_period_start
        and data.current_period_start > subscription.current_period_start
    )


# =========================================================
# EVENT HANDLERS
# =========================================================


# =========================== Subscription Created or Activated ============================== #
async def handle_subscription_sync(payload: dict, db: AsyncSession):

    try:
        # Extract values from the incoming Paddle payload
        data = SubscriptionWebhook.from_payload(payload)
        ctx = await resolve_subscription_context(data, db)
        
        if ctx.subscription is not None and _period_rolled_over(ctx.subscription, data):
            overage = calculate_overage(ctx.subscription)
            billed_ok = await bill_overage(ctx.subscription.subscription_id, overage)

            if billed_ok:
                ctx.subscription.submissions_used = 0
            else:
                log.warning(
                    f"Overage charge failed for {ctx.subscription.subscription_id} — "
                    f"leaving submissions_used unreset, will retry next sync"
                )

        if ctx.subscription is None:
            subscription = create_subscription(ctx, data, db)
        else:
            subscription = update_subscription(ctx.subscription, ctx, data)

        await save(db, subscription)
        log.info(
            f"Updated subscription for user={ctx.user.email} subscription_id={subscription.subscription_id}"
        )
        return subscription

    except Exception as e:
        log.exception(f"Unhandled error in handle_subscription_created: {e}")


# =========================== Subscription Cancelled ============================== #


async def handle_subscription_canceled(
    payload: dict,
    db: AsyncSession,
):

    try:
        data = SubscriptionWebhook.from_payload(payload)
        ctx = await resolve_subscription_context(
            data,
            db,
        )
        if ctx.subscription is None:
            log.warning(
                "Subscription not found for cancellation: %s",
                data.subscription_id,
            )
            raise SubscriptionNotFoundError("Subscription not found for cancellation")
        subscription = cancel_subscription(
            ctx.subscription,
            ctx,
            data,
        )
        await save(db, subscription)
        log.info(f"Subscription canceled {subscription.subscription_id}")

        return subscription

    except Exception as e:
        log.exception(f"Unhandled error in handle_subscription_canceled: {e}")


# =========================== Payment Failed ============================== #


async def handle_payment_failed(
    payload: dict,
    db: AsyncSession,
):
    try:
        data = PaymentFailedWebhook.from_payload(payload)
        if not data.subscription_id:
            log.warning("Payment_failed missing subscription_id")
            return None

        result = await db.execute(
            select(Subscription).where(
                Subscription.subscription_id == data.subscription_id
            )
        )
        subscription = result.scalar_one_or_none()

        if not subscription:
            log.warning(
                f"No subscription found for payment failure {data.subscription_id}"
            )
            return None

        subscription.status = SubscriptionStatus.PAST_DUE.value
        subscription.updated_at = datetime.now(UTC)

        await save(db, subscription)

        log.warning(
            f"Subscription {subscription.subscription_id} successfully marked PAST_DUE due to a bounced invoice payment."
        )

        return subscription

    except Exception as e:
        log.exception(f"Unhandled error in handle_payment_failed: {e}")


# =========================================================
# MAIN WEBHOOK ROUTER
# =========================================================


async def handle_paddle_webhook(
    event_type: str,
    payload: dict,
    db: AsyncSession,
):
    try:
        if event_type in SYNC_EVENTS:
            return await handle_subscription_sync(
                payload,
                db,
            )

        if event_type == "subscription.canceled":
            return await handle_subscription_canceled(
                payload,
                db,
            )

        if event_type == "transaction.payment_failed":
            return await handle_payment_failed(payload, db)

        log.warning(f"Unhandled Paddle webhook: {event_type}")

    except Exception as e:
        try:
            await db.rollback()
        except Exception:
            pass

        log.exception(f"Paddle webhook failed for event={event_type}: {e}")

        raise
