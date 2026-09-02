from datetime import UTC, datetime, timedelta
import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import Subscription, User
from app.schemas.user import SubscriptionStatus
from app.services.account import _format_date, get_subscription_state


def test_format_date():
    """Verify _format_date helper output."""
    dt = datetime(2026, 9, 2, tzinfo=UTC)
    formatted = _format_date(dt)
    assert formatted is not None
    assert "Sep" in formatted and "2026" in formatted
    assert _format_date(None) is None


def test_get_subscription_state_none():
    """Verify subscription state dictionary when subscription is None."""
    state = get_subscription_state(None, datetime.now(UTC))
    assert state["current_plan"] == "none"
    assert state["subscription_status"] == "inactive"
    assert state["sub_id"] is None


def test_get_subscription_state_trial():
    """Verify subscription state dictionary during active trial."""
    now = datetime.now(UTC)
    sub = Subscription(
        status="trial",
        trial_end=now + timedelta(days=5),
        price_id="none",
    )
    state = get_subscription_state(sub, now)
    assert state["trial_days_left"] == 5
