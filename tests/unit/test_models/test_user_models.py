import uuid
from datetime import datetime, timezone
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import (
    Blacklist,
    BlacklistType,
    Form,
    GoogleSheetIntegration,
    IntegrationType,
    Payment,
    PaymentStatus,
    PlanTier,
    PlanType,
    Project,
    Submission,
    SubmissionStatus,
    Subscription,
    SubscriptionStatus,
    User,
)


@pytest.mark.asyncio
async def test_user_creation_and_defaults(db_session: AsyncSession):
    """Verify User model creation, defaults, and relationships."""
    user = User(
        id=str(uuid.uuid4()),
        name="Alice Smith",
        email="alice.test@example.com",
        is_active=True,
        is_verified=False,
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)

    assert user.id is not None
    assert user.email == "alice.test@example.com"
    assert user.created_at is not None
    assert user.is_verified is False


@pytest.mark.asyncio
async def test_project_and_form_relationships(db_session: AsyncSession, sample_user: User):
    """Verify Project and Form relationship cascade."""
    project = Project(
        id=str(uuid.uuid4()),
        user_id=sample_user.id,
        name="Mobile App API",
        description="Backend forms for mobile app",
    )
    db_session.add(project)
    await db_session.commit()

    form = Form(
        id=str(uuid.uuid4()),
        project_id=project.id,
        public_id="frm_mob123",
        name="Feedback Form",
        heading="Provide feedback",
        notification_email="feedback@example.com",
    )
    db_session.add(form)
    await db_session.commit()

    result = await db_session.execute(select(Project).where(Project.id == project.id))
    fetched_project = result.scalars().first()
    assert fetched_project is not None
    assert fetched_project.user_id == sample_user.id


@pytest.mark.asyncio
async def test_submission_model_and_status(db_session: AsyncSession, sample_form: Form):
    """Verify Submission model fields and JSON data storage."""
    submission = Submission(
        id=str(uuid.uuid4()),
        form_id=sample_form.id,
        data={"first_name": "Bob", "phone": "+1234567890"},
        status=SubmissionStatus.INBOX,
        opened=True,
        is_spam=False,
    )
    db_session.add(submission)
    await db_session.commit()
    await db_session.refresh(submission)

    assert submission.data["first_name"] == "Bob"
    assert submission.status == SubmissionStatus.INBOX
    assert submission.opened is True


@pytest.mark.asyncio
async def test_blacklist_model(db_session: AsyncSession, sample_form: Form):
    """Verify Blacklist model for IP, email, domain blocking."""
    blacklist_entry = Blacklist(
        id=str(uuid.uuid4()),
        form_id=sample_form.id,
        type=BlacklistType.IP,
        value="192.168.1.100",
    )
    db_session.add(blacklist_entry)
    await db_session.commit()

    result = await db_session.execute(select(Blacklist).where(Blacklist.value == "192.168.1.100"))
    entry = result.scalars().first()
    assert entry is not None
    assert entry.type == BlacklistType.IP


@pytest.mark.asyncio
async def test_subscription_and_payment_models(db_session: AsyncSession, sample_user: User):
    """Verify Subscription and Payment models with enum plan types."""
    sub = Subscription(
        id=str(uuid.uuid4()),
        user_id=sample_user.id,
        plan_name="Pro Yearly",
        plan_type=PlanType.YEARLY,
        plan_tier=PlanTier.PRO,
        status=SubscriptionStatus.ACTIVE,
        price=190.0,
        currency="USD",
    )
    db_session.add(sub)
    await db_session.commit()

    payment = Payment(
        id=str(uuid.uuid4()),
        subscription_id=sub.id,
        amount=190.0,
        currency="USD",
        status=PaymentStatus.PAID,
        paddle_transaction_id="txn_12345",
    )
    db_session.add(payment)
    await db_session.commit()

    result = await db_session.execute(select(Payment).where(Payment.subscription_id == sub.id))
    fetched_payment = result.scalars().first()
    assert fetched_payment is not None
    assert fetched_payment.status == PaymentStatus.PAID
