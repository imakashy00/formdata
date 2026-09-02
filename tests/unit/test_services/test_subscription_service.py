import pytest

from app.schemas.user import SubscriptionStatus
from app.services.subscription import STATUS_MAP, SYNC_EVENTS, SubscriptionContext


def test_subscription_status_mapping():
    """Verify Paddle status string to SubscriptionStatus mapping."""
    assert STATUS_MAP["active"] == SubscriptionStatus.ACTIVE
    assert STATUS_MAP["trialing"] == SubscriptionStatus.TRIAL
    assert STATUS_MAP["paused"] == SubscriptionStatus.PAUSED
    assert STATUS_MAP["canceled"] == SubscriptionStatus.CANCELED


def test_sync_events_set():
    """Verify supported webhook sync events."""
    assert "subscription.created" in SYNC_EVENTS
    assert "subscription.activated" in SYNC_EVENTS
    assert "subscription.updated" in SYNC_EVENTS
