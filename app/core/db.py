import ssl

from sqlalchemy import make_url
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from app.core.settings import settings

db_url = make_url(str(settings.DATABASE_URL))

if db_url.drivername in ("postgresql", "postgres"):
    db_url = db_url.set(drivername="postgresql+asyncpg")

db_url = db_url.difference_update_query(["sslmode", "channel_binding"])

# 2. Check if connecting to Neon. If yes, require SSL.
connect_args = {}
if db_url.host and "neon.tech" in db_url.host:
    connect_args["ssl"] = ssl.create_default_context()

engine = create_async_engine(
    db_url,
    # echo=(
    #     settings.ENV == "development"
    # ),  # Prints generated SQL queries to the console/logs. in dev mode
    pool_pre_ping=True,  # Before using a DB connection from the pool, SQLAlchemy checks if it’s still alive.
    pool_size=settings.DB_POOL_SIZE,  # Number of persistent DB connections kept open.
    max_overflow=settings.DB_MAX_OVERFLOW,  # Allows temporary extra connections beyond pool_size.
    connect_args=connect_args,
)

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
