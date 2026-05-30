from typing import Optional

from pydantic import BaseModel, ValidationError

from app.models.user import Subscription, User
from datetime import datetime, timezone
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from loguru import logger as log
import httpx

from app.core.settings import settings
from app.routes import subscription
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

async def get_customer_email(customer_id: str)-> str| None:
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{settings.PADDLE_BASE_URL}/customers/{customer_id}",
                headers=headers
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


async def get_user_by_customer_id(
    customer_id: str,
    db: AsyncSession
):
    try:
        user_email = await get_customer_email(customer_id)
        if not user_email: 
            return None

        query_result = await db.execute(select(User).where(User.email == user_email))
        return query_result.scalars().first()
    except Exception as e:
        log.error(f"Error finding user by Paddle customer id {customer_id}: {e} ")
        return None




async def get_subscription_by_user_id(
    user_id: str,
    db: AsyncSession
):

    try:
        query_result = await db.execute(select(Subscription).where(Subscription.user_id == user_id))
        return query_result.scalars().first()
    except Exception as e:
        log.error(f"Error finding Subscription by user id {user_id}: {e} ")
        return None


def extract_subscription_data(payload: dict):

    subscription_data = payload.get("data",{}) or {}
    subscription_id = subscription_data.get("id")
    customer_id = subscription_data.get("customer_id")        
    status = subscription_data.get("status")
    items = subscription_data.get("items") or []
    first_item = items[0] if items else {}
    price_id = first_item.get("price",{}).get("id")
    
    billing_cycle = first_item.get("billling_cycle") or {}
    interval = billing_cycle.get("interval")
    current_billing_period = subscription_data.get("current_billing_period") or {}

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
        "status": status,
        "price_id": price_id,
        "plan_interval": interval,
        "current_period_start": parse_dt(current_billing_period.get("starts_at")),
        "current_period_end": parse_dt(current_billing_period.get("ends_at")),
        "cancel_at": parse_dt(subscription_data.get("scheduled_change", {}).get("effective_at")),
        "canceled_at": parse_dt(subscription_data.get("canceled_at")),
    }


# =========================================================
# EVENT HANDLERS
# =========================================================

async def handle_subscription_created(
    payload: dict,
    db: AsyncSession
):
    """
    EVENT:
    subscription.created

    WHAT THIS EVENT MEANS:
    - Paddle created subscription object
    - User may still be in trial
    - Payment may not yet be completed

    TODO:
    - Extract subscription data
    - Find user
    - Create subscription row if not exists
    - Store:
        - subscription_id
        - customer_id
        - status
        - price_id
        - plan_interval
        - billing periods
    - If row already exists:
        - update values
    - Commit transaction

    IMPORTANT:
    - Do NOT assume subscription is active yet
    - Status can be trialing
    """

    pass


async def handle_subscription_activated(
    payload: dict,
    db: AsyncSession
):
    """
    EVENT:
    subscription.activated

    WHAT THIS EVENT MEANS:
    - Subscription became active
    - First payment succeeded
    - User should now have premium access

    TODO:
    - Extract subscription data
    - Find user
    - Find existing subscription row
    - Update:
        - status -> ACTIVE
        - current_period_start
        - current_period_end
        - price_id
        - plan_interval
        - updated_at
    - Clear:
        - cancel_at
        - canceled_at
    - Commit transaction
    """

    pass


async def handle_subscription_updated(
    payload: dict,
    db: AsyncSession
):
    """
    EVENT:
    subscription.updated

    WHAT THIS EVENT MEANS:
    - Plan changed
    - Billing cycle changed
    - Status changed
    - Renewal dates changed
    - Quantity changed

    TODO:
    - Extract latest subscription values
    - Find subscription row
    - Update changed fields:
        - status
        - price_id
        - plan_interval
        - billing periods
        - updated_at

    IMPORTANT:
    - This event is very common
    - Treat Paddle as source of truth
    """

    pass


async def handle_subscription_canceled(
    payload: dict,
    db: AsyncSession
):
    """
    EVENT:
    subscription.canceled

    WHAT THIS EVENT MEANS:
    - User canceled auto-renew
    - User may STILL have access until period end

    TODO:
    - Find subscription
    - Set:
        - status -> CANCELED
        - cancel_at -> current_period_end
        - canceled_at -> now
        - updated_at -> now

    IMPORTANT:
    - Do NOT revoke access immediately
    - Access should continue until cancel_at
    """

    pass


async def handle_subscription_past_due(
    payload: dict,
    db: AsyncSession
):
    """
    EVENT:
    subscription.past_due

    WHAT THIS EVENT MEANS:
    - Payment failed temporarily
    - Paddle will retry payment

    TODO:
    - Find subscription
    - Update status -> PAST_DUE
    - Store updated_at timestamp

    OPTIONAL:
    - Notify user by email
    - Show warning banner in frontend

    IMPORTANT:
    - User may still temporarily retain access
    - Depends on your business logic
    """

    pass


async def handle_subscription_resumed(
    payload: dict,
    db: AsyncSession
):
    """
    EVENT:
    subscription.resumed

    WHAT THIS EVENT MEANS:
    - Previously canceled subscription resumed
    - Auto-renew enabled again

    TODO:
    - Find subscription
    - Set:
        - status -> ACTIVE
        - cancel_at -> None
        - canceled_at -> None
        - updated_at -> now

    OPTIONAL:
    - Refresh billing dates from payload
    """

    pass


async def handle_subscription_paused(
    payload: dict,
    db: AsyncSession
):
    """
    EVENT:
    subscription.paused

    WHAT THIS EVENT MEANS:
    - Subscription temporarily paused
    - Billing suspended

    TODO:
    - Find subscription
    - Update:
        - status -> PAUSED
        - updated_at -> now

    OPTIONAL:
    - Restrict premium access
    - Show paused message in frontend
    """

    pass


async def handle_transaction_paid(
    payload: dict,
    db: AsyncSession
):
    """
    EVENT:
    transaction.paid

    WHAT THIS EVENT MEANS:
    - Payment/invoice succeeded

    TODO:
    - Extract:
        - transaction_id
        - customer_id
        - subscription_id
        - amount
        - currency

    POSSIBLE USE CASES:
    - Store invoice/payment history table
    - Generate receipt
    - Send confirmation email
    - Analytics
    - Revenue tracking

    OPTIONAL:
    - Verify subscription status is ACTIVE
    """

    pass


async def handle_payment_failed(
    payload: dict,
    db: AsyncSession
):
    """
    EVENT:
    transaction.payment_failed

    WHAT THIS EVENT MEANS:
    - Charge failed
    - Card declined
    - Insufficient funds
    - Expired card

    TODO:
    - Find related subscription
    - Mark:
        - status -> PAST_DUE
        - updated_at -> now

    OPTIONAL:
    - Send email asking user to update card
    - Show payment failure warning
    - Log failure reason from payload
    """

    pass


# =========================================================
# MAIN WEBHOOK ROUTER
# =========================================================

async def handle_paddle_webhook(
    event_type: str,
    payload: dict,
    db: AsyncSession
):
    """
    Central Paddle webhook router

    TODO:
    - Use match-case on event_type
    - Route to correct handler
    - Log unknown events
    - Raise errors for unexpected failures
    """

    try:

        match event_type:

            case "subscription.created":
                # TODO:
                # call handle_subscription_created
                pass

            case "subscription.activated":
                # TODO:
                # call handle_subscription_activated
                pass

            case "subscription.updated":
                # TODO:
                # call handle_subscription_updated
                pass

            case "subscription.canceled":
                # TODO:
                # call handle_subscription_canceled
                pass

            case "subscription.past_due":
                # TODO:
                # call handle_subscription_past_due
                pass

            case "subscription.resumed":
                # TODO:
                # call handle_subscription_resumed
                pass

            case "subscription.paused":
                # TODO:
                # call handle_subscription_paused
                pass

            case "transaction.paid":
                # TODO:
                # call handle_transaction_paid
                pass

            case "transaction.payment_failed":
                # TODO:
                # call handle_payment_failed
                pass

            case _:
                # TODO:
                # log unknown/unhandled webhook event
                # don't crash webhook for unsupported events
                pass

    except Exception as e:
        """
        TODO:
        - Log full webhook failure
        - Rollback transaction if needed
        - Re-raise exception
        - Return 500 so Paddle retries webhook
        """

        raise