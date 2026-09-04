from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User


@pytest.mark.asyncio
async def test_get_account_page_authenticated(
    client: AsyncClient,
    auth_cookies: dict,
    sample_user: User,
    db_session: AsyncSession,
):
    """Verify GET /account renders the user account settings and billing dashboard."""
    with patch(
        "app.routes.account.get_account_billing_data", new_callable=AsyncMock
    ) as mock_billing:
        mock_billing.return_value = {
            "current_plan": "starter",
            "subscription_status": "active",
            "sub_id": "sub_123",
            "renews_at": "Sep 20, 2026",
            "resumes_at": None,
            "trial_days_left": None,
            "cancel_at": None,
            "can_undo_cancel": False,
            "portal_links": {"overview_url": "https://paddle.com/portal"},
            "submission_quota": {
                "usage": 10,
                "limit": 1000,
                "percentage": 1,
                "extra": 0,
            },
            "storage_quota": {
                "used_bytes": 0,
                "limit_bytes": 2147483648,
                "percentage": 0,
                "extra_bytes": 0,
            },
        }
        response = await client.get("/account", cookies=auth_cookies)
        assert response.status_code == 200
        assert "Account" in response.text or "billing" in response.text.lower()
