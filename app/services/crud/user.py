from datetime import UTC, datetime

from fastapi import HTTPException, status
from loguru import logger as log
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import Subscription, User
from app.schemas.user import RegisterUser, SubscriptionStatus


async def register_user(userinfo: RegisterUser, db: AsyncSession):
    try:
        result = await db.execute(
            select(User).filter(User.google_sub == userinfo.google_sub)
        )
        db_user = result.scalars().first()

        if db_user:
            db_user.last_login = datetime.now(UTC)
            await db.commit()
            await db.refresh(db_user)
            return db_user.id

        # 1. Initialize the new user (Do not commit yet)
        new_user = User(
            name=userinfo.name,
            email=userinfo.email,
            google_sub=userinfo.google_sub,
            picture=userinfo.picture,
            last_login=datetime.now(UTC),
        )
        db.add(new_user)

        # 2. Flush to generate new_user.id without finalizing the transaction
        await db.flush()

        # 3. Initialize the subscription using the flushed user ID
        # Added .value to fix the Enum serialization crash found in your logs
        subscription = Subscription(
            user_id=new_user.id,
            status=SubscriptionStatus.TRIAL.value,
        )
        db.add(subscription)

        # 4. Commit once. If either step fails, the entire transaction rolls back.
        await db.commit()
        return new_user.id

    except SQLAlchemyError as e:
        await db.rollback()
        log.error(f"Database transaction failed during registration: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Database error occurred while registering user.",
        )