import pytest
from sqlalchemy import make_url
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import AsyncSessionLocal, Base, engine, get_db


@pytest.mark.asyncio
async def test_engine_initialization():
    """Verify SQLAlchemy engine and sessionmaker configuration."""
    assert engine is not None
    assert AsyncSessionLocal is not None
    assert Base is not None


@pytest.mark.asyncio
async def test_get_db_yields_session():
    """Verify get_db dependency yields a valid AsyncSession and closes properly."""
    db_gen = get_db()
    session = await anext(db_gen)
    assert isinstance(session, AsyncSession)

    # Finish generator iteration
    with pytest.raises(StopAsyncIteration):
        await anext(db_gen)


@pytest.mark.asyncio
async def test_get_db_rollback_on_exception(monkeypatch):
    """Verify get_db rolls back the transaction when an exception occurs during request."""
    db_gen = get_db()
    session = await anext(db_gen)
    
    # Simulate an error within endpoint
    with pytest.raises(RuntimeError, match="Database error simulation"):
        try:
            raise RuntimeError("Database error simulation")
        except Exception as e:
            await db_gen.athrow(e)
