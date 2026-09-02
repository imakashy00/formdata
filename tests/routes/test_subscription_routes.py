import pytest
from httpx import AsyncClient

from app.routes.subscription import CURRENCY_SYMBOLS, PLAN_ORDER


def test_plan_order_and_currency():
    """Verify subscription plan ordering and currency symbol mapping."""
    assert PLAN_ORDER["trial"] < PLAN_ORDER["solo"] < PLAN_ORDER["studio"]
    assert CURRENCY_SYMBOLS["USD"] == "$"
    assert CURRENCY_SYMBOLS["EUR"] == "€"


@pytest.mark.asyncio
async def test_paddle_webhook_invalid_signature(client: AsyncClient):
    """Verify POST /subscription/webhook rejects requests with missing or invalid signature."""
    response = await client.post(
        "/subscription/webhook",
        json={"event_type": "subscription.created", "data": {}},
    )
    assert response.status_code in (400, 401, 403, 422)
