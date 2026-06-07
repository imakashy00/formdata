from typing import Optional
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base
from app.schemas.user import SubscriptionStatus


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    google_sub: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    picture: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    last_login: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    subscription: Mapped["Subscription"] = relationship(  # noqa: F821 # type: ignore
        "Subscription",
        back_populates="user",
        uselist=False,
        cascade="all, delete-orphan",
    )

    @property
    def has_access(self) -> bool:
        sub = self.subscription
        return sub.has_access if sub else False


class Subscription(Base):
    __tablename__ = "subscriptions"
    __table_args__ = (
        UniqueConstraint("user_id", name="uq_subscriptions_user_id"),  # enforce 1:1
        Index("ix_sub_subscription_id", "subscription_id"),
        Index("ix_sub_price_id", "price_id"),
    )

    id: Mapped[str] = mapped_column(
        String, primary_key=True, default=lambda: str(uuid.uuid4())
    )
    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    paddle_customer_id: Mapped[str | None] = mapped_column(
        String(255), unique=True, nullable=True
    )
    user: Mapped["User"] = relationship(back_populates="subscription")  # noqa: F821 # type: ignore
    subscription_id: Mapped[Optional[str]] = mapped_column(
        String(255), unique=True, nullable=True
    )
    price_id: Mapped[Optional[str]] = mapped_column(
        String(255), nullable=True
    )  # Paddle Price ID
    plan_interval: Mapped[Optional[str]] = mapped_column(  # 'monthly' or 'yearly'
        String(10), nullable=True
    )
    # Status (align with Paddle statuses you map in webhooks)
    status: Mapped[str] = mapped_column(
        String(30), default=SubscriptionStatus.TRIAL, nullable= False
    )  # trial | active | canceled

    trial_end: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc) + timedelta(days=15),
    )

    # Billing period windows (from Paddle)
    current_period_start: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    current_period_end: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # Cancellation
    cancel_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    canceled_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # Flags and timestamps
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    @property
    def has_access(self) -> bool:
        """Determine if the user currently has access based on subscription state."""
        now = datetime.now(timezone.utc)

        # 1️⃣ Trial period — valid until trial_end
        if self.status == SubscriptionStatus.TRIAL.value:
            return self.trial_end and now < self.trial_end

        # 2️⃣ Active subscription — valid until the end of the billing period
        if self.status == SubscriptionStatus.ACTIVE.value:
            # If current_period_end is known, enforce it
            if self.current_period_end:
                return now < self.current_period_end
            # Otherwise assume still valid
            return True

        # 3️⃣ Canceled subscription — access until cancel_at (end of billing period)
        if self.status == SubscriptionStatus.CANCELED.value and self.cancel_at:
            return now < self.cancel_at

        # ❌ Otherwise, access revoked
        return False
