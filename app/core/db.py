from app.core.settings import settings
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

engine = create_async_engine(
    str(settings.DATABASE_URL),
    echo=(settings.ENV == "development"), # Prints generated SQL queries to the console/logs. in dev mode
    pool_pre_ping=True, # Before using a DB connection from the pool, SQLAlchemy checks if it’s still alive.
    pool_size=settings.DB_POOL_SIZE, # Number of persistent DB connections kept open.
    max_overflow=settings.DB_MAX_OVERFLOW, # Allows temporary extra connections beyond pool_size.
)

AsyncSessionLocal = async_sessionmaker(
    bind=engine, class_=AsyncSession, expire_on_commit=False
)


class Base(DeclarativeBase):
    pass


async def get_db():
    async with AsyncSessionLocal() as db:
        yield db
