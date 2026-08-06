from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.core.templates import temp
from app.models.user import Form as FormDB
from app.models.user import Project, Submission, Subscription, User
from app.routes.page import get_current_user

account_router = APIRouter()


@account_router.get("/account", response_class=HTMLResponse)
async def handle_get_account_details(
    request: Request,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    now = datetime.now(UTC)
    quota_limit = getattr(user, "submission_quota", 5000)
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

    quota_usage = (
        await db.scalar(
            select(func.count(Submission.id))
            .select_from(Submission)
            .join(FormDB, Submission.form_id == FormDB.id)
            .join(Project, FormDB.project_id == Project.id)
            .where(Project.user_id == user.id)
            .where(Submission.created_at >= month_start)
        )
        or 0
    )

    quota_percentage = (
        min(int((quota_usage / quota_limit) * 100), 100) if quota_limit > 0 else 100
    )
    sub_query = select(Subscription).filter(Subscription.user_id == user.id)
    result = await db.execute(sub_query)
    subscription = result.scalar_one_or_none()

    if not subscription:
        raise HTTPException(status_code=400, detail="No active subscription found.")

    return temp.TemplateResponse(
        request,
        "account.html",
        {
            "email": user.email,
            "name": user.name,
            "sub_id": subscription.subscription_id,
            "user_id": user.id,
            "page": "account",
            "quota_usage": quota_usage,
            "quota_limit": quota_limit,
            "quota_percentage": quota_percentage,
        },
    )
