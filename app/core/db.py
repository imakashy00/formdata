import socket
import ssl

from sqlalchemy import event, make_url
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

import app.core.sqlite_compat
from app.core.sqlite_compat import register_sqlite_functions
from app.core.settings import settings

db_url = make_url(str(settings.DATABASE_URL))


def _is_postgres_available(host: str | None, port: int | None) -> bool:
    if not host:
        return False
    try:
        with socket.create_connection((host, port or 5432), timeout=0.5):
            return True
    except (OSError, socket.timeout):
        return False


is_sqlite = False

if db_url.drivername.startswith("postgresql") or db_url.drivername.startswith("postgres"):
    if db_url.host in ("localhost", "127.0.0.1", None) and not _is_postgres_available(
        db_url.host, db_url.port
    ):
        # Fallback to SQLite for local dev when PostgreSQL is not running
        db_url = make_url("sqlite+aiosqlite:///./formdata.db")
        is_sqlite = True
    else:
        db_url = db_url.set(drivername="postgresql+asyncpg")
elif db_url.drivername.startswith("sqlite"):
    is_sqlite = True

if not is_sqlite:
    db_url = db_url.difference_update_query(["sslmode", "channel_binding"])
    connect_args = {}
    if db_url.host and "neon.tech" in db_url.host:
        connect_args["ssl"] = ssl.create_default_context()

    engine = create_async_engine(
        db_url,
        pool_pre_ping=True,
        pool_size=settings.DB_POOL_SIZE,
        max_overflow=settings.DB_MAX_OVERFLOW,
        connect_args=connect_args,
    )
else:
    connect_args = {"check_same_thread": False}
    engine = create_async_engine(
        db_url,
        connect_args=connect_args,
    )

    @event.listens_for(engine.sync_engine, "connect")
    def on_sqlite_connect(dbapi_conn, _):
        register_sqlite_functions(dbapi_conn)

AsyncSessionLocal = async_sessionmaker(
    bind=engine, class_=AsyncSession, expire_on_commit=False
)


class Base(DeclarativeBase):
    pass


async def get_db():
    async with AsyncSessionLocal() as db:
        try:
            yield db
        except Exception:
            await db.rollback()
            raise
        finally:
            await db.close()
