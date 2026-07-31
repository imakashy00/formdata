import math
from dataclasses import dataclass

import httpx
from app.core.settings import settings
from app.models.user import Subscription
from loguru import logger as log

headers = {
    "Authorization": f"Bearer {settings.PADDLE_API_KEY!s}",
    "Accept": "application/json",
}

BYTES_PER_GB = 1024**3
SUBMISSION_BLOCK = 200

PLAN_LIMITS: dict[str, dict[str, int]] = {
    settings.PADDLE_PRICE_ID_SOLO: {"submissions": 1000, "storage_gb": 0},
    settings.PADDLE_PRICE_ID_STUDIO: {"submissions": 2000, "storage_gb": 2},
}


@dataclass(slots=True)
class Overage:
    submission_blocks: int
    storage_gb: int

    @property
    def has_charge(self) -> bool:
        return self.submission_blocks > 0 or self.storage_gb > 0


def calculate_overage(subscription: Subscription) -> Overage:
    if subscription.price_id in PLAN_LIMITS:
        limits = PLAN_LIMITS[subscription.price_id]
    else:
        limits = {"submissions": 0, "storage_gb": 0}

    # limits = PLAN_LIMITS.get(subscription.price_id, {"submissions": 0, "storage_gb": 0})

    extra_submissions = max(0, subscription.submissions_used - limits["submissions"])
    submission_blocks = -(-extra_submissions // SUBMISSION_BLOCK)  # ceil division

    used_gb = subscription.storage_bytes_used / BYTES_PER_GB
    extra_storage_gb = max(0, math.ceil(used_gb - limits["storage_gb"]))

    return Overage(submission_blocks=submission_blocks, storage_gb=extra_storage_gb)


async def bill_overage(subscription_id: str | None, overage: Overage) -> bool:
    if not overage.has_charge:
        return (
            True  # nothing to bill this period — still a "success", counters can reset
        )

    if not subscription_id:
        log.warning("Skipping overage billing because subscription_id is missing")
        return False

    items = []
    if overage.submission_blocks:
        items.append(
            {
                "price_id": settings.PADDLE_PRICE_ID_EXTRA_SUBMISSIONS,
                "quantity": overage.submission_blocks,
            }
        )
    if overage.storage_gb:
        items.append(
            {
                "price_id": settings.PADDLE_PRICE_ID_EXTRA_STORAGE,
                "quantity": overage.storage_gb,
            }
        )

    async with httpx.AsyncClient(base_url="https://api.paddle.com") as client:
        resp = await client.post(
            f"/subscriptions/{subscription_id}/charge",
            headers=headers,
            json={"effective_from": "immediately", "items": items},
        )

    if resp.status_code >= 400:
        log.error(
            f"Overage charge failed for {subscription_id}: {resp.status_code} {resp.text}"
        )
        return False

    log.info(
        f"Billed overage for {subscription_id}: "
        f"{overage.submission_blocks} submission block(s), {overage.storage_gb}GB extra storage"
    )
    return True