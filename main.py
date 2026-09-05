import asyncio
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Response
from fastapi.staticfiles import StaticFiles
from sqlalchemy import text
from starlette.middleware.sessions import SessionMiddleware

from app.core.db import AsyncSessionLocal, Base, engine
import app.models.user  # noqa: F401 - Register models with Base.metadata
from app.core.logger import setup_logger
from app.core.middlewares.exception_handlers import register_exception_handlers
from app.core.middlewares.middleware import register_middlewares
from app.core.middlewares.rate_limit import cleanup_expired_buckets, rate_limit
from app.core.settings import settings
from app.routes.account import account_router
from app.routes.auth import auth_router
from app.routes.client_form import client_form_router
from app.routes.dashboard import dash_router
from app.routes.form import form_router
from app.routes.form_setting import form_settings_router
from app.routes.page import page_router
from app.routes.project import project_router
from app.routes.resend_email import email_router
from app.routes.subscription import user_router
from app.services.blacklist import cleanup_expired

log = setup_logger()


async def _cleanup_loop():
    while True:
        try:
            async with AsyncSessionLocal() as db:
                tokens_deleted = await cleanup_expired(db)
                buckets_deleted = await cleanup_expired_buckets(db)
            if tokens_deleted or buckets_deleted:
                log.info(
                    f"🧹 Cleanup: removed {tokens_deleted} expired auth_tokens, "
                    f"{buckets_deleted} stale rate_limit_buckets."
                )
        except Exception as e:
            log.warning(f"⚠️ Cleanup task skipped or failed: {e}")

        await asyncio.sleep(settings.CLEANUP_INTERVAL_SECONDS)


def start_cleanup_task():
    """Starts the background loop, returns a function to cancel it on shutdown."""
    task = asyncio.create_task(_cleanup_loop())
    return task.cancel


async def verify_services() -> None:
    """Verify database connection and ensure tables exist."""
    try:
        async with engine.connect() as connection:
            await connection.execute(text("SELECT 1"))
        log.info("✅ Postgres is reachable.")

        # Ensure all tables (including auth_tokens) exist in the database
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        log.info("✅ Postgres schema initialized/verified.")
    except Exception as exc:
        log.error(f"❌ Postgres is not reachable: {exc}")
        if settings.ENV != "development":
            raise


@asynccontextmanager
async def lifespan(app: FastAPI):
    log.info("🚀 Starting up...")
    await verify_services()
    cleanup_task = asyncio.create_task(_cleanup_loop())
    yield
    log.info("🛑 Shutting down...")
    cleanup_task.cancel()
    try:
        await cleanup_task
    except asyncio.CancelledError:
        pass
    await engine.dispose()


# Disable docs in production
docs_url = None if settings.ENV == "production" else "/docs"
redoc_url = None if settings.ENV == "production" else "/redoc"

app = FastAPI(
    lifespan=lifespan,
    docs_url=docs_url,
    redoc_url=redoc_url,
    title="Formdata WebApp",
    debug=(settings.ENV == "development"),
    dependencies=[
        Depends(rate_limit(limit=100, window_seconds=60)),
    ],
)

# Register exception handlers
register_exception_handlers(app)

# Add rate limiting


app.add_middleware(SessionMiddleware, secret_key=settings.SESSION_SECRET)

app.include_router(router=auth_router)
app.include_router(router=page_router)
app.include_router(router=user_router)
app.include_router(router=account_router)
app.include_router(router=form_router)
app.include_router(router=form_settings_router)
app.include_router(router=project_router)
app.include_router(router=dash_router)
app.include_router(router=email_router)
app.include_router(router=client_form_router)
app.mount("/static", StaticFiles(directory="app/static"), name="static")


# register your moved middlewares
register_middlewares(app)


@app.get("/health")
async def health_check() -> Response:
    return Response(status_code=200, content="OK")
