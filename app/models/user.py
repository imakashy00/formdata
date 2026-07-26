import secrets
import uuid
from datetime import UTC, datetime, timedelta
from enum import Enum as PyEnum

from sqlalchemy import (
    Boolean,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base
from app.schemas.user import SubscriptionStatus


class SubmissionStatus(str, PyEnum):
    ACCEPTED = "accepted"
    REJECTED = "rejected"


def generate_short_id() -> str:
    # Generates a highly secure URL-safe 8-character text token
    return secrets.token_urlsafe(6)[:8]


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
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )
    last_login: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    projects: Mapped[list["Project"]] = relationship(
        "Project",
        back_populates="user",
        cascade="all, delete-orphan",
    )
    subscription: Mapped["Subscription"] = relationship(  # type: ignore
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
    user: Mapped["User"] = relationship(back_populates="subscription")  # type: ignore
    subscription_id: Mapped[str | None] = mapped_column(
        String(255), unique=True, nullable=True
    )
    price_id: Mapped[str | None] = mapped_column(
        String(255), nullable=True
    )  # Paddle Price ID
    plan_interval: Mapped[str | None] = mapped_column(  # 'monthly' or 'yearly'
        String(10), nullable=True
    )
    submissions_used: Mapped[int] = mapped_column(
        default=0, nullable=False
    )  # resets each period
    storage_bytes_used: Mapped[int] = mapped_column(
        default=0, nullable=False
    )  # running total, not reset
    # Status (align with Paddle statuses you map in webhooks)
    status: Mapped[str] = mapped_column(
        String(30), default=SubscriptionStatus.TRIAL.value, nullable=False
    )  # trial | active | canceled

    trial_end: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC) + timedelta(days=15),
    )

    # Billing period windows (from Paddle)
    current_period_start: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    current_period_end: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # Cancellation
    cancel_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    canceled_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # Flags and timestamps
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
    )

    @property
    def has_access(self) -> bool:
        """Determine if the user currently has access based on subscription state."""
        now = datetime.now(UTC)

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


class ProcessedWebhook(Base):
    __tablename__ = "processed_webhooks"

    # Paddle's root 'event_id' is a completely unique string (e.g., 'evt_01kwq...')
    event_id: Mapped[str] = mapped_column(String(255), primary_key=True)

    # Helpful metadata for debugging or clean-up crons later
    event_type: Mapped[str] = mapped_column(String(100), nullable=False)
    processed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )


class OverageCharge(Base):
    __tablename__ = "overage_charges"

    id: Mapped[int] = mapped_column(primary_key=True)
    subscription_id: Mapped[str] = mapped_column(String)
    submission_blocks: Mapped[int] = mapped_column(Integer)
    storage_gb: Mapped[int] = mapped_column(Integer)
    amount_cents: Mapped[int] = mapped_column(Integer)
    billed_at: Mapped[datetime] = mapped_column(DateTime)


class Project(Base):
    __tablename__ = "projects"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    # Connect project directly to the parent User
    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )

    name: Mapped[str] = mapped_column(String(100), nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
    )

    # Relationships
    user: Mapped["User"] = relationship(back_populates="projects")  # Link to User model
    forms: Mapped[list["Form"]] = relationship(
        "Form",
        order_by="desc(Form.updated_at), desc(Form.created_at)",
        back_populates="project",
        cascade="all, delete-orphan",  # Deleting a project automatically wipes its forms
    )


class Form(Base):
    __tablename__ = "forms"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    name: Mapped[str] = mapped_column(String(150), nullable=False)
    public_id: Mapped[str] = mapped_column(
        String(8), unique=True, index=True, nullable=False, default=generate_short_id
    )
    # Forms belong to a Project, which implicitly links them to a User
    project_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    honeypot: Mapped[str] = mapped_column(String(36), nullable=False, default="_gotcha")
    allowed_domains: Mapped[list[str]] = mapped_column(
        ARRAY(String), server_default="{}"
    )
    redirect_url: Mapped[str | None] = mapped_column(String(2083), nullable=True)
    notification_email: Mapped[str | None] = mapped_column(String(255), nullable=True)

    turnstile_secret: Mapped[str | None] = mapped_column(String(255), nullable=True)

    # Store form structures, fields, inputs, or schemas easily using raw strings or a JSON block
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    sub_message: Mapped[str] = mapped_column(
        String(200), nullable=False, server_default="Submission successful!"
    )
    sub_bg_color: Mapped[str] = mapped_column(
        String(7), nullable=False, server_default="#ffffff"
    )
    sub_txt_color: Mapped[str] = mapped_column(
        String(7), nullable=False, server_default="#000000"
    )
    sub_lnk_color: Mapped[str] = mapped_column(
        String(7), nullable=False, server_default="#3b82f6"
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
    )

    # Relationships
    project: Mapped["Project"] = relationship(back_populates="forms")
    submissions: Mapped[list["Submission"]] = relationship(
        "Submission",
        back_populates="form",
        order_by="desc(Submission.created_at)",
        cascade="all, delete-orphan",
    )


class Submission(Base):
    __tablename__ = "submissions"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    form_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("forms.id", ondelete="CASCADE"), nullable=False
    )

    # 4. Dynamic Payload Storage (PostgreSQL JSONB)
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False)

    status: Mapped[SubmissionStatus] = mapped_column(
        Enum(
            SubmissionStatus,
            values_callable=lambda enum_cls: [e.value for e in enum_cls],
            name="submissionstatus",
        ),
        nullable=False,
        default=SubmissionStatus.ACCEPTED,
        server_default=SubmissionStatus.ACCEPTED.value,
        index=True,
    )

    country_code: Mapped[str | None] = mapped_column(String(2), nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )

    form: Mapped["Form"] = relationship("Form", back_populates="submissions")
