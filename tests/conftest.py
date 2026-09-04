import asyncio
import os
import uuid
import socket
from collections.abc import AsyncGenerator
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, patch

import pytest

# 1. Set testing environment variables before importing settings/app
os.environ["ENV"] = "development"
os.environ["BASE_URL"] = "http://localhost:3000"
os.environ["CLEANUP_INTERVAL_SECONDS"] = "3600"
os.environ["SESSION_SECRET"] = "test-session-secret-key-32-chars-long!"
if "DATABASE_URL" not in os.environ:
    os.environ["DATABASE_URL"] = (
        "postgresql+asyncpg://imakashy00:password@localhost:5432/formdata"
    )
os.environ["DB_POOL_SIZE"] = "5"
os.environ["DB_MAX_OVERFLOW"] = "10"
os.environ["JWT_ALGO"] = "HS256"
os.environ["JWT_SECRET"] = "test-jwt-secret-key-for-testing-only-12345"
os.environ["ACCESS_TTL_MIN"] = "15"
os.environ["REFRESH_TTL_MIN"] = "10080"
os.environ["GOOGLE_CLIENT_ID"] = "test-google-client-id"
os.environ["GOOGLE_CLIENT_SECRET"] = "test-google-client-secret"
os.environ["PADDLE_API_KEY"] = "test-paddle-api-key"
os.environ["PADDLE_WEBHOOK_SECRET"] = "test-paddle-webhook-secret"
os.environ["PADDLE_BASE_URL"] = "https://sandbox-api.paddle.com"
os.environ["PADDLE_PRICE_ID_SOLO"] = "pri_solo_test"
os.environ["PADDLE_PRICE_ID_STUDIO"] = "pri_studio_test"
os.environ["PADDLE_CLIENT_TOKEN"] = "test_paddle_token"
os.environ["PADDLE_ENVIRONMENT"] = "sandbox"
os.environ["RESEND_API_KEY"] = "re_test_123456789"
os.environ["FROM_EMAIL"] = "notifications@formdata.space"
os.environ["FROM_NAME"] = "Formdata"
os.environ["MAX_UPLOAD_BYTES"] = "10485760"
os.environ["MAX_FILES_PER_SUBMISSION"] = "5"
os.environ["R2_ACCOUNT_ID"] = "test-r2-account-id"
os.environ["R2_ACCESS_KEY_ID"] = "test-r2-access-key-id"
os.environ["R2_SECRET_ACCESS_KEY"] = "test-r2-secret-access-key"
os.environ["R2_BUCKET"] = "test-bucket"

from httpx import ASGITransport, AsyncClient
from sqlalchemy import event, make_url
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.pool import NullPool, StaticPool

import app.core.sqlite_compat
from app.core.sqlite_compat import register_sqlite_functions


def _is_postgres_available(host: str | None, port: int | None) -> bool:
    if not host:
        return False
    try:
        with socket.create_connection((host, port or 5432), timeout=0.5):
            return True
    except (OSError, socket.timeout):
        return False


db_url = make_url(os.environ["DATABASE_URL"])
is_postgres = False
if db_url.drivername.startswith("postgresql") or db_url.drivername.startswith("postgres"):
    if db_url.host not in ("localhost", "127.0.0.1", None) or _is_postgres_available(
        db_url.host, db_url.port
    ):
        is_postgres = True

if is_postgres:
    test_engine = create_async_engine(
        db_url.set(drivername="postgresql+asyncpg"),
        echo=False,
        poolclass=NullPool,
    )
else:
    test_engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        echo=False,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    @event.listens_for(test_engine.sync_engine, "connect")
    def on_sqlite_connect(dbapi_conn, _):
        register_sqlite_functions(dbapi_conn)

TestingSessionLocal = async_sessionmaker(
    bind=test_engine, class_=AsyncSession, expire_on_commit=False
)

from app.core.db import Base, get_db
from app.models.user import (
    Form,
    Project,
    Submission,
    SubmissionStatus,
    Subscription,
    User,
)
from app.services.jwt import create_token
from main import app


@pytest.fixture(autouse=True)
async def init_db():
    """Create all tables before each test and drop them after."""
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


@pytest.fixture
async def db_session() -> AsyncGenerator[AsyncSession]:
    """Provide a transactional asynchronous DB session for tests."""
    async with TestingSessionLocal() as session:
        yield session


@pytest.fixture
async def client(db_session: AsyncSession) -> AsyncGenerator[AsyncClient]:
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
        id=uuid.uuid4(),
        name="John Doe",
        email="john.doe@example.com",
        google_sub="goog_123456789",
        is_active=True,
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user


@pytest.fixture
async def sample_subscription(
    db_session: AsyncSession, sample_user: User
) -> Subscription:
    """Create and return a sample subscription for the test user."""
    subscription = Subscription(
        id=uuid.uuid4(),
        user_id=sample_user.id,
        status="active",
        price_id="pri_solo_test",
        paddle_customer_id="ctm_test_12345",
        subscription_id="sub_test_12345",
        trial_end=datetime.now(UTC) + timedelta(days=15),
    )
    db_session.add(subscription)
    await db_session.commit()
    await db_session.refresh(subscription)
    return subscription


@pytest.fixture
def auth_headers(sample_user: User) -> dict:
    """Return Authorization Bearer headers for the sample user."""
    token, _, _ = create_token(
        sub=str(sample_user.id),
        email=sample_user.email,
        type="access",
        ttl=timedelta(minutes=15),
    )
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def auth_cookies(sample_user: User) -> dict:
    """Return auth cookies for the sample user."""
    token, _, _ = create_token(
        sub=str(sample_user.id),
        email=sample_user.email,
        type="access",
        ttl=timedelta(minutes=15),
    )
    return {"access_token": token}


@pytest.fixture
async def sample_project(db_session: AsyncSession, sample_user: User) -> Project:
    """Create and return a sample project."""
    project = Project(
        id=uuid.uuid4(),
        user_id=sample_user.id,
        name="Production Website",
    )
    db_session.add(project)
    await db_session.commit()
    await db_session.refresh(project)
    return project


@pytest.fixture
async def sample_form(db_session: AsyncSession, sample_project: Project) -> Form:
    """Create and return a sample form with trial subscription for owner."""
    user_id = sample_project.user_id
    from sqlalchemy import select
    from app.models.user import Subscription, SubscriptionStatus
    existing_sub = await db_session.execute(
        select(Subscription).where(Subscription.user_id == user_id)
    )
    if not existing_sub.scalars().first():
        sub = Subscription(
            id=uuid.uuid4(),
            user_id=user_id,
            status=SubscriptionStatus.TRIAL.value,
            trial_end=datetime.now(UTC) + timedelta(days=15),
        )
        db_session.add(sub)
        await db_session.flush()

    form = Form(
        id=uuid.uuid4(),
        project_id=sample_project.id,
        public_id="frm_test",
        name="Contact Us",
        heading="Get in touch with us",
        notification_email="notify@example.com",
        is_active=True,
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
        id=uuid.uuid4(),
        form_id=sample_form.id,
        payload={
            "name": "Alice Smith",
            "email": "alice@example.com",
            "message": "Hello world",
        },
        status=SubmissionStatus.ACCEPTED,
        opened=False,
        note=None,
        country="United States",
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
    with patch("resend.Emails.send_async", new_callable=AsyncMock) as mock_send_async, patch(
        "resend.Emails.send"
    ) as mock_send:
        mock_send_async.return_value = {"id": "email_msg_12345", "status": "sent"}
        mock_send.return_value = {"id": "email_msg_12345", "status": "sent"}
        yield mock_send_async


@pytest.fixture
def mock_s3():
    """Mock S3 / Cloudflare R2 file uploads."""
    with patch("aioboto3.Session") as mock_session:
        client_mock = AsyncMock()
        client_mock.upload_fileobj = AsyncMock()
        client_mock.generate_presigned_url = AsyncMock(
            return_value="https://r2.example.com/signed-url"
        )
        client_mock.delete_object = AsyncMock()
        mock_session.return_value.client.return_value.__aenter__.return_value = (
            client_mock
        )
        yield client_mock

