from sqlalchemy.exc import SQLAlchemyError
from fastapi import HTTPException, status
from datetime import datetime, timezone
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from loguru import logger as log
from app.schemas.user import RegisterUser, SubscriptionStatus
from app.models.user import User, Subscription


async def register_user(userinfo: RegisterUser, db: AsyncSession):
    try:
        result = await db.execute(
            select(User).filter(User.google_sub == userinfo.google_sub)
        )
        db_user = result.scalars().first()

        if db_user:
            db_user.last_login = datetime.now(timezone.utc)
            await db.commit()
            await db.refresh(db_user)
            return db_user.id

        # Create new user
        new_user = User(
            name=userinfo.name,
            email=userinfo.email,
            google_sub=userinfo.google_sub,
            picture=userinfo.picture,
            last_login=datetime.now(timezone.utc),
        )

        db.add(new_user)
        await db.commit()
        await db.refresh(new_user)
        subscription = Subscription(
            user_id=new_user.id,
            status=SubscriptionStatus.TRIAL,
        )
        db.add(subscription)
        await db.commit()
        return new_user.id

    except SQLAlchemyError as e:
        await db.rollback()
        log.error("Adding user to database failed")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Database error occured at while registering user:{e}",
        )
