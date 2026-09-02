import pytest
from pydantic import ValidationError

from app.schemas.user import DBUser, RegisterUser, SubscriptionStatus


def test_register_user_schema_valid():
    """Verify RegisterUser schema with valid parameters."""
    user = RegisterUser(
        name="Charlie Test",
        email="charlie@example.com",
        google_sub="google-12345",
        picture="https://example.com/pic.jpg",
    )
    assert user.name == "Charlie Test"
    assert user.email == "charlie@example.com"
    assert user.google_sub == "google-12345"


def test_register_user_schema_invalid_email():
    """Verify RegisterUser raises error on invalid email."""
    with pytest.raises(ValidationError):
        RegisterUser(
            name="Charlie",
            email="not-an-email",
            google_sub="google-12345",
        )


def test_db_user_schema():
    """Verify DBUser schema attributes."""
    db_user = DBUser(id="user_123", email="user@example.com", jti="jti_456")
    assert db_user.id == "user_123"
    assert db_user.email == "user@example.com"
    assert db_user.jti == "jti_456"


def test_subscription_status_enum():
    """Verify SubscriptionStatus enum values."""
    assert SubscriptionStatus.ACTIVE.value == "active"
    assert SubscriptionStatus.TRIAL.value == "trial"
    assert SubscriptionStatus.PAUSED.value == "paused"
    assert SubscriptionStatus.CANCELED.value == "canceled"
