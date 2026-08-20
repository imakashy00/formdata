import math
from dataclasses import dataclass

import httpx
from loguru import logger as log

from app.core.settings import settings
from app.models.user import Subscription

headers = {
    "Authorization": f"Bearer {settings.PADDLE_API_KEY!s}",
    "Content-Type": "application/json",
    "Accept": "application/json",
}

BYTES_PER_GB = 1024**3
SUBMISSION_BLOCK = 200
OVERAGE_UNIT_AMOUNT_CENTS = "100"  # $1 per submission-block, $1 per extra GB
OVERAGE_CURRENCY = "USD"

# Monthly submission allowances per plan (mirrors the copy on the pricing
# cards in account.html: "1,000 submissions / month" / "2,000 / month").
PLAN_SUBMISSION_QUOTAS = {
    "solo": 1000,
    "studio": 2000,
}

PLAN_LIMITS: dict[str, dict[str, int]] = {
    settings.PADDLE_PRICE_ID_SOLO: {"submissions": 1000, "storage_gb": 0},
    settings.PADDLE_PRICE_ID_STUDIO: {"submissions": 2000, "storage_gb": 2},
}
# Storage is a Studio-only feature per the pricing cards ("File uploads" is
# an X on Solo). 2GB baseline is included; extra is billed at $1/GB/month,
# but there's no column yet tracking purchased extra storage — see note below.
# PLAN_STORAGE_LIMITS_BYTES = {
#     "studio": 2 * 1024**3,
# }


# Keyed by price_id (what's stored on the subscription) so bill_overage can
# look up "which product is this customer's plan attached to" in one step.
PLAN_PRODUCT_IDS: dict[str, str] = {
    settings.PADDLE_PRICE_ID_SOLO: settings.PADDLE_PRICE_ID_SOLO,
    settings.PADDLE_PRICE_ID_STUDIO: settings.PADDLE_PRICE_ID_STUDIO,
}


@dataclass(slots=True)
class Overage:
    submission_blocks: int
    storage_gb: int

    @property
    def has_charge(self) -> bool:
        return self.submission_blocks > 0 or self.storage_gb > 0


def calculate_overage(subscription: Subscription) -> Overage:

    limits = PLAN_LIMITS.get(
        subscription.price_id or "", {"submissions": 0, "storage_gb": 0}
    )

    extra_submissions = max(0, subscription.submissions_used - limits["submissions"])
    submission_blocks = -(-extra_submissions // SUBMISSION_BLOCK)  # ceil division

    used_gb = subscription.storage_bytes_used / BYTES_PER_GB
    extra_storage_gb = max(0, math.ceil(used_gb - limits["storage_gb"]))

    return Overage(submission_blocks=submission_blocks, storage_gb=extra_storage_gb)


async def bill_overage(subscription: Subscription, overage: Overage) -> bool:
    """Bills overage as non-catalog prices attached to the product the
    customer is already subscribed to (Solo or Studio), rather than a
    separate catalog price — so no PADDLE_PRICE_ID_EXTRA_* is needed."""
    if not overage.has_charge:
        return True  # nothing to bill this period — still a "success"

    if not subscription.subscription_id:
        log.warning("Skipping overage billing because subscription_id is missing")
        return False

    product_id = PLAN_PRODUCT_IDS.get(subscription.price_id or "trial")
    if not product_id:
        log.error(
            f"Skipping overage billing for {subscription.subscription_id}: "
            f"no product mapped for price_id {subscription.price_id!r}"
        )
        return False

    items = []
    if overage.submission_blocks:
        items.append(
            {
                "quantity": overage.submission_blocks,
                "price": {
                    "product_id": product_id,
                    "description": "Overage — extra submissions",
                    "name": f"Extra submissions ({overage.submission_blocks * SUBMISSION_BLOCK})",
                    "unit_price": {
                        "amount": OVERAGE_UNIT_AMOUNT_CENTS,
                        "currency_code": OVERAGE_CURRENCY,
                    },
                },
            }
        )
    if overage.storage_gb:
        items.append(
            {
                "quantity": overage.storage_gb,
                "price": {
                    "product_id": product_id,
                    "description": "Overage — extra storage",
                    "name": f"Extra storage ({overage.storage_gb} GB)",
                    "unit_price": {
                        "amount": OVERAGE_UNIT_AMOUNT_CENTS,
                        "currency_code": OVERAGE_CURRENCY,
                    },
                },
            }
        )
    url = f"{settings.PADDLE_BASE_URL}/subscriptions/{subscription.subscription_id}/charge"
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            url,
            headers=headers,
            json={"effective_from": "immediately", "items": items},
        )

    if resp.status_code >= 400:
        log.error(
            f"Overage charge failed for {subscription.subscription_id}: "
            f"{resp.status_code} {resp.text}"
        )
        return False

    log.info(
        f"Billed overage for {subscription.subscription_id}: "
        f"{overage.submission_blocks} submission block(s), {overage.storage_gb}GB extra storage"
    )
    return True
