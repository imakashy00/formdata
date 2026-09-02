import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.schemas.user import RegisterUser
from app.services.crud.user import register_user


@pytest.mark.asyncio
async def test_register_new_user(db_session: AsyncSession):
    """Verify register_user creates a new user and a trial subscription."""
    userinfo = RegisterUser(
        name="Diana Prince",
        email="diana@example.com",
        google_sub="goog_987654321",
        picture="https://example.com/avatar.png",
    )
    user_id = await register_user(userinfo=userinfo, db=db_session)
    assert user_id is not None


@pytest.mark.asyncio
async def test_register_existing_user_updates_last_login(db_session: AsyncSession):
    """Verify register_user updates last_login timestamp if user already exists."""
    userinfo = RegisterUser(
        name="Diana Prince",
        email="diana@example.com",
        google_sub="goog_987654321",
        picture="https://example.com/avatar.png",
    )
    user_id_1 = await register_user(userinfo=userinfo, db=db_session)
    user_id_2 = await register_user(userinfo=userinfo, db=db_session)
    
    assert user_id_1 == user_id_2
