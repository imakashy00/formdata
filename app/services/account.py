import httpx
from loguru import logger as log

from app.core.settings import settings


async def get_customer_portal_links(customer_id: str, subscription_id: str) -> dict:
    """
    Dynamically generates fresh, authenticated Paddle portal links.
    These contain temporary login tokens and must not be cached.
    """
    url = f"{settings.PADDLE_BASE_URL}/customers/{customer_id}/portal-sessions"
    headers = {
        "Authorization": f"Bearer {settings.PADDLE_API_KEY}",
        "Content-Type": "application/json",
    }
    payload = {"subscription_ids": [subscription_id]}

    try:
        # Using httpx async client context manager
        async with httpx.AsyncClient() as client:
            response = await client.post(url, headers=headers, json=payload)

            # Raise an exception for HTTP errors (4xx or 5xx)
            response.raise_for_status()

            data = response.json()["data"]

            # Extract the deep links safely
            return {
                "overview_url": data["urls"]["general"]["overview"],
                "cancel_url": data["urls"]["subscriptions"][0]["cancel_subscription"],
                "update_payment_url": data["urls"]["subscriptions"][0][
                    "update_subscription_payment_method"
                ],
            }
    except Exception as e:
        log.error(f"Error fetching customer payment management links{e}")
        return {
            "overview_url": "#",
            "cancel_url": "#",
            "update_payment_url": "#",
        }
