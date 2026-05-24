from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from sqlalchemy import text
from starlette.middleware.sessions import SessionMiddleware

from app.core.db import engine
from app.core.settings import settings
from app.logger import setup_logger
from app.middlewares.exception_handlers import register_exception_handlers
from app.middlewares.middleware import register_middlewares
from app.middlewares.rate_limit import setup_rate_limiting
from app.routes.auth import router
from app.routes.page import page_router
from app.routes.subscription import user_router
from app.services.blacklist import redis_client

log = setup_logger()


async def verify_services() -> None:
    try:
        async with engine.connect() as connection:
            await connection.execute(text("SELECT 1"))
        log.info("✅ Postgres is reachable.")
    except Exception as exc:
        log.error(f"❌ Postgres is not reachable: {exc}")
        raise

    try:
        await redis_client.ping()
        log.info("✅ Redis is reachable.")
    except Exception as exc:
        log.error(f"❌ Redis is not reachable: {exc}")
        raise


@asynccontextmanager
async def lifespan(app: FastAPI):
    log.info("🚀 Starting up...")
    await verify_services()
    yield
    log.info("🛑 Shutting down...")
    await engine.dispose()
    await redis_client.close()


# Disable docs in production
docs_url = None if settings.ENV == "production" else "/docs"
redoc_url = None if settings.ENV == "production" else "/redoc"

app = FastAPI(
    lifespan=lifespan,
    docs_url=docs_url,
    redoc_url=redoc_url,
    title="YTranscript API",
    debug=(settings.ENV == "development"),
)

# Register exception handlers
register_exception_handlers(app)

# Add rate limiting
setup_rate_limiting(app)

app.add_middleware(SessionMiddleware, secret_key=settings.SECRET)

app.include_router(router=router)
app.include_router(router=page_router)
app.include_router(router=user_router)
app.mount("/static", StaticFiles(directory="app/static"), name="static")


# register your moved middlewares
register_middlewares(app)
