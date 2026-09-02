import uuid
from datetime import UTC, datetime, timedelta
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import (
    AuthToken,
    BLACKLIST,
    WHITELIST,
    Form,
    FormIntegration,
    Integration,
    IntegrationProvider,
    Project,
    Submission,
    SubmissionStatus,
    Subscription,
    User,
)


@pytest.mark.asyncio
async def test_user_creation_and_defaults(db_session: AsyncSession):
    """Verify User model creation, defaults, and relationships."""
    user = User(
        id=uuid.uuid4(),
        name="Alice Smith",
        email="alice.test@example.com",
        google_sub="goog_alice_999",
        is_active=True,
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)

    assert user.id is not None
    assert user.email == "alice.test@example.com"
    assert user.created_at is not None
    assert user.is_active is True


@pytest.mark.asyncio
async def test_project_and_form_relationships(db_session: AsyncSession, sample_user: User):
    """Verify Project and Form relationship cascade."""
    project = Project(
        id=uuid.uuid4(),
        user_id=sample_user.id,
        name="Mobile App API",
    )
    db_session.add(project)
    await db_session.commit()

    form = Form(
        id=uuid.uuid4(),
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
    """Verify Submission model fields and JSON payload storage."""
    submission = Submission(
        id=uuid.uuid4(),
        form_id=sample_form.id,
        payload={"first_name": "Bob", "phone": "+1234567890"},
        status=SubmissionStatus.ACCEPTED,
        opened=True,
    )
    db_session.add(submission)
    await db_session.commit()
    await db_session.refresh(submission)

    assert submission.payload["first_name"] == "Bob"
    assert submission.status == SubmissionStatus.ACCEPTED
    assert submission.opened is True


@pytest.mark.asyncio
async def test_auth_token_model(db_session: AsyncSession, sample_user: User):
    """Verify AuthToken model for whitelist and blacklist tracking."""
    token = AuthToken(
        jti="jti_test_12345",
        user_id=sample_user.id,
        token_type=WHITELIST,
        expires_at=datetime.now(UTC) + timedelta(days=7),
    )
    db_session.add(token)
    await db_session.commit()

    result = await db_session.execute(select(AuthToken).where(AuthToken.jti == "jti_test_12345"))
    entry = result.scalars().first()
    assert entry is not None
    assert entry.token_type == WHITELIST


@pytest.mark.asyncio
async def test_subscription_model(db_session: AsyncSession, sample_user: User):
    """Verify Subscription model trial and active states."""
    sub = Subscription(
        id=uuid.uuid4(),
        user_id=sample_user.id,
        status="trial",
        price_id="none",
        trial_end=datetime.now(UTC) + timedelta(days=15),
    )
    db_session.add(sub)
    await db_session.commit()

    result = await db_session.execute(select(Subscription).where(Subscription.user_id == sample_user.id))
    fetched_sub = result.scalars().first()
    assert fetched_sub is not None
    assert fetched_sub.has_access is True

