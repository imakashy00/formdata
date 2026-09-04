import secrets
import uuid
from datetime import UTC, datetime, timedelta
from enum import Enum as PyEnum

from sqlalchemy import TIMESTAMP, CheckConstraint, Index, Integer, String, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base

WHITELIST = "whitelist"
BLACKLIST = "blacklist"
from sqlalchemy import (
    Boolean,
    DateTime,
    Enum,
    ForeignKey,
    Text,
    UniqueConstraint,
    func,
    select,
)
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import column_property, relationship

from app.schemas.user import SubscriptionStatus


class SubmissionStatus(str, PyEnum):
    ACCEPTED = "accepted"
    REJECTED = "rejected"


UUID_PRIMARY_KEY = {"primary_key": True, "server_default": text("gen_random_uuid()")}


def generate_short_id() -> str:
    # Generates a highly secure URL-safe 8-character text token
    return secrets.token_urlsafe(6)[:8]


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), **UUID_PRIMARY_KEY)
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

    id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), **UUID_PRIMARY_KEY)

    user_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
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

        def _to_utc(dt: datetime | None) -> datetime | None:
            if dt is None:
                return None
            return dt if dt.tzinfo else dt.replace(tzinfo=UTC)

        # 1️⃣ Trial period — valid until trial_end
        if self.status == SubscriptionStatus.TRIAL.value:
            trial_end = _to_utc(self.trial_end)
            return bool(trial_end and now < trial_end)

        # 2️⃣ Active subscription — valid until the end of the billing period
        if self.status == SubscriptionStatus.ACTIVE.value:
            # If current_period_end is known, enforce it
            current_period_end = _to_utc(self.current_period_end)
            if current_period_end:
                return now < current_period_end
            # Otherwise assume still valid
            return True

        # 3️⃣ Canceled subscription — access until cancel_at (end of billing period)
        if self.status == SubscriptionStatus.CANCELED.value and self.cancel_at:
            cancel_at = _to_utc(self.cancel_at)
            return bool(cancel_at and now < cancel_at)

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

    id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), **UUID_PRIMARY_KEY)
    subscription_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("subscriptions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    submission_blocks: Mapped[int] = mapped_column(Integer)
    storage_gb: Mapped[int] = mapped_column(Integer)
    amount_cents: Mapped[int] = mapped_column(Integer)
    billed_at: Mapped[datetime] = mapped_column(DateTime)


class Project(Base):
    __tablename__ = "projects"

    id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), **UUID_PRIMARY_KEY)

    # Connect project directly to the parent User
    user_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
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

    id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), **UUID_PRIMARY_KEY)

    name: Mapped[str] = mapped_column(String(150), nullable=False)
    heading: Mapped[str | None] = mapped_column(String(200), nullable=True)
    public_id: Mapped[str] = mapped_column(
        String(8), unique=True, index=True, nullable=False, default=generate_short_id
    )
    # Forms belong to a Project, which implicitly links them to a User
    project_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    honeypot: Mapped[str] = mapped_column(String(36), nullable=False, default="_gotcha")

    # TODO: Add constraints on the String and arary size of the allowed domains
    allowed_domains: Mapped[list[str]] = mapped_column(
        ARRAY(String), server_default="{}", default=list
    )
    redirect: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    redirect_url: Mapped[str | None] = mapped_column(String(2083), nullable=True)
    notification_email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    autoresponse: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    duplicate_allowed: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True
    )
    duplicate_check_input: Mapped[str | None] = mapped_column(
        String(100), nullable=True
    )
    turnstile_enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )
    turnstile_secret: Mapped[str | None] = mapped_column(String(255), nullable=True)

    # Add these inside your Form class definition

    # Template configurations sent to your users' customers
    customer_subject: Mapped[str] = mapped_column(
        String(255), nullable=False, server_default="Submission Received."
    )
    customer_body: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        server_default="Hi,\n\nThank you for reaching out! We received your submission.",
    )

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

    submissions_count: Mapped[int] = column_property(
        select(func.count())
        .select_from(text("submissions"))
        .where(text("submissions.form_id = forms.id"))
        .scalar_subquery()
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

    id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), **UUID_PRIMARY_KEY)

    form_id: Mapped[str] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("forms.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # 4. Dynamic Payload Storage (PostgreSQL JSONB)
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False)

    integration_sync_status: Mapped[dict] = mapped_column(
        JSONB,
        default=dict,
        nullable=False,
    )

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
    opened: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    note: Mapped[str | None] = mapped_column(String(200), nullable=True)
    country: Mapped[str | None] = mapped_column(String(100), nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )

    form: Mapped["Form"] = relationship("Form", back_populates="submissions")

    @property
    def integration_sync_state(self) -> str:
        status_map = self.integration_sync_status or {}
        states = [
            entry.get("state")
            for entry in status_map.values()
            if isinstance(entry, dict)
        ]

        if not states:
            return "not_synced"
        if any(state == "failed" for state in states):
            return "failed"
        if any(state in {"pending", "queued", "awaiting_auth"} for state in states):
            return "pending"
        if all(state == "synced" for state in states):
            return "synced"
        return "partial"

    @property
    def integration_sync_summary(self) -> str | None:
        status_map = self.integration_sync_status or {}
        if not status_map:
            return None

        parts: list[str] = []
        for provider, entry in status_map.items():
            if not isinstance(entry, dict):
                continue

            state = entry.get("state")
            message = entry.get("message")
            if state == "synced":
                parts.append(f"{provider}: synced")
            elif state == "failed":
                parts.append(f"{provider}: failed")
            elif state == "awaiting_auth":
                parts.append(f"{provider}: auth required")
            elif state == "pending":
                parts.append(f"{provider}: pending")
            elif message:
                parts.append(f"{provider}: {message}")

        return ", ".join(parts) if parts else None


class IntegrationProvider(str, PyEnum):
    GOOGLE_SHEETS = "google_sheets"
    NOTION = "notion"
    SLACK = "slack"


class Integration(Base):
    __tablename__ = "integrations"

    id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), **UUID_PRIMARY_KEY)

    user_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    provider: Mapped[IntegrationProvider] = mapped_column(
        Enum(IntegrationProvider, name="integrationprovider"),
        nullable=False,
    )

    # OAuth access token
    access_token: Mapped[str | None] = mapped_column(Text)

    # OAuth refresh token where applicable
    refresh_token: Mapped[str | None] = mapped_column(Text)

    # Provider-specific information
    integration_metadata: Mapped[dict] = mapped_column(
        JSONB,
        default=dict,
        nullable=False,
    )

    enabled: Mapped[bool] = mapped_column(
        Boolean,
        default=True,
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )


class FormIntegration(Base):
    __tablename__ = "form_integrations"
    __table_args__ = (
        UniqueConstraint(
            "form_id", "integration_id", name="uq_form_integrations_form_integration"
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), **UUID_PRIMARY_KEY)

    form_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("forms.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    integration_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("integrations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    config: Mapped[dict] = mapped_column(
        JSONB,
        default=dict,
        nullable=False,
    )

    enabled: Mapped[bool] = mapped_column(
        Boolean,
        default=True,
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )


class AuthToken(Base):
    """One row per refresh-token JTI. `token_type` says whether the row is
    an active refresh token (whitelist) or an explicitly revoked token
    (blacklist). A jti goes whitelist -> deleted on normal rotation, or
    whitelist -> blacklist on explicit revoke (see token_store.revoke)."""

    __tablename__ = "auth_tokens"
    __table_args__ = (
        CheckConstraint(
            "token_type IN ('whitelist', 'blacklist')", name="ck_auth_tokens_token_type"
        ),
        Index("ix_auth_tokens_expires_at", "expires_at"),
        Index("ix_auth_tokens_user_id", "user_id"),
        {"prefixes": ["UNLOGGED"]},
    )

    jti: Mapped[str] = mapped_column(String, primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    token_type: Mapped[str] = mapped_column(String, nullable=False)
    email: Mapped[str | None] = mapped_column(String, nullable=True)
    expires_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True),
        nullable=False,
        server_default=text("now()"),
        default=lambda: datetime.now(UTC),
    )
    # Free-form extras (device info, revoke reason, etc.) without a migration
    # every time you want to attach something new to a token row.
    meta: Mapped[dict] = mapped_column(
        JSONB,
        nullable=False,
        server_default=text("'{}'::jsonb"),
        default=dict,
    )


class RateLimitBucket(Base):
    """Fixed-window rate-limit counter: one row per (bucket_key, window_start).
    `bucket_key` is typically f"{client_ip}:{route}" or just the client IP."""

    __tablename__ = "rate_limit_buckets"

    __table_args__ = ({"prefixes": ["UNLOGGED"]},)

    bucket_key: Mapped[str] = mapped_column(String, primary_key=True)
    window_start: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), primary_key=True
    )
    request_count: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("1"), default=1
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )


class ThankYouToken(Base):
    __tablename__ = "thankyoutokens"

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        **UUID_PRIMARY_KEY,
    )

    token_hash: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        unique=True,
    )

    submission_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("submissions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    expires_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True),
        nullable=False,
    )

    used_at: Mapped[datetime | None] = mapped_column(
        TIMESTAMP(timezone=True),
        nullable=True,
    )
