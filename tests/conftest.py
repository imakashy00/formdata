import asyncio
import os
import uuid
from typing import AsyncGenerator
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

# Set testing environment variables before importing settings/app
os.environ["ENV"] = "development"
os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///:memory:"
os.environ["REDIS_URL"] = "redis://localhost:6379/0"
os.environ["JWT_SECRET_KEY"] = "test-secret-key-1234567890-test-secret"
os.environ["RESEND_API_KEY"] = "re_test_123456789"
os.environ["GOOGLE_CLIENT_ID"] = "test-google-id"
os.environ["GOOGLE_CLIENT_SECRET"] = "test-google-secret"
os.environ["GITHUB_CLIENT_ID"] = "test-github-id"
os.environ["GITHUB_CLIENT_SECRET"] = "test-github-secret"
os.environ["PADDLE_API_KEY"] = "test-paddle-key"
os.environ["PADDLE_WEBHOOK_SECRET_KEY"] = "test-paddle-webhook-secret"

from app.core.db import Base, get_db
from app.core.settings import settings
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
from app.services.jwt import create_access_token
from main import app

# Test Engine for SQLite in-memory
test_engine = create_async_engine(
    "sqlite+aiosqlite:///:memory:",
    echo=False,
)

TestingSessionLocal = async_sessionmaker(
    bind=test_engine, class_=AsyncSession, expire_on_commit=False
)


@pytest.fixture(scope="session")
def event_loop():
    """Create an instance of the default event loop for each test case."""
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()


@pytest.fixture(autouse=True)
async def init_db():
    """Create all tables before each test and drop them after."""
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


@pytest.fixture
async def db_session() -> AsyncGenerator[AsyncSession, None]:
    """Provide a transactional asynchronous DB session for tests."""
    async with TestingSessionLocal() as session:
        yield session


@pytest.fixture
async def client(db_session: AsyncSession) -> AsyncGenerator[AsyncClient, None]:
    """Provide an AsyncClient for FastAPI endpoint testing with DB dependency overridden."""
    async def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac

    app.dependency_overrides.clear()


@pytest.fixture
async def sample_user(db_session: AsyncSession) -> User:
    """Create and return a sample user in DB."""
    user = User(
        id=str(uuid.uuid4()),
        name="John Doe",
        email="john.doe@example.com",
        is_active=True,
        is_verified=True,
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user


@pytest.fixture
async def sample_subscription(db_session: AsyncSession, sample_user: User) -> Subscription:
    """Create and return a sample subscription for the test user."""
    subscription = Subscription(
        id=str(uuid.uuid4()),
        user_id=sample_user.id,
        plan_name="Starter Monthly",
        plan_type=PlanType.MONTHLY,
        plan_tier=PlanTier.STARTER,
        status=SubscriptionStatus.ACTIVE,
        price=19.0,
        currency="USD",
        paddle_subscription_id="sub_test_12345",
        paddle_customer_id="ctm_test_12345",
    )
    db_session.add(subscription)
    await db_session.commit()
    await db_session.refresh(subscription)
    return subscription


@pytest.fixture
def auth_headers(sample_user: User) -> dict:
    """Return Authorization Bearer headers for the sample user."""
    token = create_access_token(data={"sub": sample_user.id, "email": sample_user.email})
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def auth_cookies(sample_user: User) -> dict:
    """Return auth cookies for the sample user."""
    token = create_access_token(data={"sub": sample_user.id, "email": sample_user.email})
    return {"access_token": token}


@pytest.fixture
async def sample_project(db_session: AsyncSession, sample_user: User) -> Project:
    """Create and return a sample project."""
    project = Project(
        id=str(uuid.uuid4()),
        user_id=sample_user.id,
        name="Production Website",
        description="Main marketing site",
    )
    db_session.add(project)
    await db_session.commit()
    await db_session.refresh(project)
    return project


@pytest.fixture
async def sample_form(db_session: AsyncSession, sample_project: Project) -> Form:
    """Create and return a sample form."""
    form = Form(
        id=str(uuid.uuid4()),
        project_id=sample_project.id,
        public_id="frm_" + uuid.uuid4().hex[:8],
        name="Contact Us",
        heading="Get in touch with us",
        notification_email="notify@example.com",
        email_notification=True,
        is_active=True,
        spam_protection=True,
        redirect_url="https://example.com/thank-you",
    )
    db_session.add(form)
    await db_session.commit()
    await db_session.refresh(form)
    return form


@pytest.fixture
async def sample_submission(db_session: AsyncSession, sample_form: Form) -> Submission:
    """Create and return a sample submission."""
    submission = Submission(
        id=str(uuid.uuid4()),
        form_id=sample_form.id,
        data={"name": "Alice Smith", "email": "alice@example.com", "message": "Hello world"},
        status=SubmissionStatus.INBOX,
        opened=False,
        is_spam=False,
        spam_score=0.1,
        ip_address="127.0.0.1",
        user_agent="Mozilla/5.0 Test",
        country_code="US",
        country_name="United States",
    )
    db_session.add(submission)
    await db_session.commit()
    await db_session.refresh(submission)
    return submission


@pytest.fixture
def mock_redis():
    """Mock Redis client for rate limiting and cache."""
    mock = AsyncMock()
    mock.get.return_value = None
    mock.set.return_value = True
    mock.setex.return_value = True
    mock.incr.return_value = 1
    mock.expire.return_value = True
    mock.delete.return_value = 1
    mock.keys.return_value = []
    return mock


@pytest.fixture
def mock_resend():
    """Mock Resend email API calls."""
    with patch("resend.Emails.send") as mock_send:
        mock_send.return_value = {"id": "email_msg_12345", "status": "sent"}
        yield mock_send


@pytest.fixture
def mock_s3():
    """Mock S3 / Cloudflare R2 file uploads."""
    with patch("aioboto3.Session") as mock_session:
        client_mock = AsyncMock()
        client_mock.upload_fileobj = AsyncMock()
        client_mock.generate_presigned_url = AsyncMock(return_value="https://r2.example.com/signed-url")
        client_mock.delete_object = AsyncMock()
        mock_session.return_value.client.return_value.__aenter__.return_value = client_mock
        yield client_mock
