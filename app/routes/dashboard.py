from datetime import datetime, timedelta, timezone
from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.models.user import User, Project, Submission, Form as FormDB
from app.routes.page import get_current_user
from app.core.templates import temp

dash_router = APIRouter()


async def _get_dashboard_summary(db: AsyncSession, user: User) -> dict:
    user_id = user.id
    now = datetime.now(timezone.utc)
    cutoff_24h = now - timedelta(hours=24)

    # ----------------------------------------------------
    # 1. Base Workspace Metric Counters & Forms Splitting
    # ----------------------------------------------------
    projects_count = await db.scalar(
        select(func.count(Project.id)).where(Project.user_id == user_id)
    )

    # Group counts by Form status (Active vs Paused)
    forms_query = await db.execute(
        select(FormDB.is_active, func.count(FormDB.id))
        .select_from(FormDB)
        .join(Project, FormDB.project_id == Project.id)
        .where(Project.user_id == user_id)
        .group_by(FormDB.is_active)
    )
    forms_rows = forms_query.all()
    forms_status_map = {row[0]: row[1] for row in forms_rows}

    active_forms = forms_status_map.get(True, 0)
    paused_forms = forms_status_map.get(False, 0)
    forms_count = active_forms + paused_forms

    submissions_count = await db.scalar(
        select(func.count(Submission.id))
        .select_from(Submission)
        .join(FormDB, Submission.form_id == FormDB.id)
        .join(Project, FormDB.project_id == Project.id)
        .where(Project.user_id == user_id)
    )

    submissions_last_24h = await db.scalar(
        select(func.count(Submission.id))
        .select_from(Submission)
        .join(FormDB, Submission.form_id == FormDB.id)
        .join(Project, FormDB.project_id == Project.id)
        .where(Project.user_id == user_id)
        .where(Submission.created_at >= cutoff_24h)
    )

    # ----------------------------------------------------
    # 2. Tier 1: Resource Quota Usage Analytics Tracker
    # ----------------------------------------------------
    quota_limit = getattr(user, "submission_quota", 5000)
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

    quota_usage = (
        await db.scalar(
            select(func.count(Submission.id))
            .select_from(Submission)
            .join(FormDB, Submission.form_id == FormDB.id)
            .join(Project, FormDB.project_id == Project.id)
            .where(Project.user_id == user_id)
            .where(Submission.created_at >= month_start)
        )
        or 0
    )
    quota_percentage = (
        min(int((quota_usage / quota_limit) * 100), 100) if quota_limit > 0 else 100
    )

    # ----------------------------------------------------
    # 3. Tier 1: 7-Day Timeline Submission Trend Line Generator
    # ----------------------------------------------------
    trend_labels = []
    trend_values = []
    for i in reversed(range(7)):
        day_date = (now - timedelta(days=i)).date()
        day_start = datetime.combine(day_date, datetime.min.time(), tzinfo=timezone.utc)
        day_end = datetime.combine(day_date, datetime.max.time(), tzinfo=timezone.utc)

        count = (
            await db.scalar(
                select(func.count(Submission.id))
                .select_from(Submission)
                .join(FormDB, Submission.form_id == FormDB.id)
                .join(Project, FormDB.project_id == Project.id)
                .where(Project.user_id == user_id)
                .where(Submission.created_at.between(day_start, day_end))
            )
            or 0
        )
        trend_labels.append(day_date.strftime("%b %d"))
        trend_values.append(count)

    # ----------------------------------------------------
    # 4. Tier 1: Top Active Form Fields Breakdown List
    # ----------------------------------------------------
    sub_count_expr = func.count(Submission.id)
    top_forms_query = await db.execute(
        select(FormDB.id, FormDB.name, sub_count_expr.label("sub_count"))
        .join(Submission, Submission.form_id == FormDB.id)
        .join(Project, FormDB.project_id == Project.id)
        .where(Project.user_id == user_id)
        .group_by(FormDB.id, FormDB.name)
        # 🟢 FIX: order by the actual count expression, not a bare string label
        .order_by(sub_count_expr.desc())
        .limit(5)
    )
    top_forms = [
        {"id": f.id, "name": f.name, "count": f.sub_count}
        for f in top_forms_query.all()
    ]

    # ----------------------------------------------------
    # 5. Tier 2: Anti-Spam Protection Gateway Filter Analytics
    # ----------------------------------------------------
    spam_query = await db.execute(
        select(Submission.spam_provider, func.count(Submission.id))
        .join(FormDB, Submission.form_id == FormDB.id)
        .join(Project, FormDB.project_id == Project.id)
        .where(Project.user_id == user_id)
        .where(Submission.status == "rejected")
        .group_by(Submission.spam_provider)
    )
    spam_rows = spam_query.all()
    spam_map = {str(row[0]): int(row[1]) for row in spam_rows if row[0] is not None}

    spam_stats = {
        "honeypot": spam_map.get("honeypot", 0),
        "altcha": spam_map.get("altcha", 0),
        "turnstile": spam_map.get("turnstile", 0),
        "total": sum(spam_map.values()),
    }

    # ----------------------------------------------------
    # 6. Tier 2: Real-time Live Activity Feeds Pipeline
    # ----------------------------------------------------
    recent_accepted_query = await db.execute(
        select(Submission, FormDB.name.label("form_name"))
        .join(FormDB, Submission.form_id == FormDB.id)
        .join(Project, FormDB.project_id == Project.id)
        .where(Project.user_id == user_id)
        .where(Submission.status == "accepted")
        .order_by(Submission.created_at.desc())
        .limit(5)
    )
    recent_submissions = [
        {
            "sender_name": s.Submission.sender_name or "Anonymous",
            "sender_email": s.Submission.sender_email or "No Email",
            "form_name": s.form_name,
            "created_at": s.Submission.created_at.strftime("%Y-%m-%d %H:%M"),
        }
        for s in recent_accepted_query.all()
    ]

    recent_rejected_query = await db.execute(
        select(Submission, FormDB.name.label("form_name"))
        .join(FormDB, Submission.form_id == FormDB.id)
        .join(Project, FormDB.project_id == Project.id)
        .where(Project.user_id == user_id)
        .where(Submission.status == "rejected")
        .order_by(Submission.created_at.desc())
        .limit(5)
    )
    failed_submissions = [
        {
            "sender_name": s.Submission.sender_name or "Spam Bot",
            "sender_email": s.Submission.sender_email or "N/A",
            "form_name": s.form_name,
            "reason": s.Submission.spam_provider or "Triggered Rule",
            "created_at": s.Submission.created_at.strftime("%Y-%m-%d %H:%M"),
        }
        for s in recent_rejected_query.all()
    ]

    return {
        "projects_count": projects_count or 0,
        "forms_count": forms_count,
        "active_forms": active_forms,
        "paused_forms": paused_forms,
        "submissions_count": submissions_count or 0,
        "submissions_last_24h": submissions_last_24h or 0,
        "quota_usage": quota_usage,
        "quota_limit": quota_limit,
        "quota_percentage": quota_percentage,
        "trend_labels": trend_labels,
        "trend_values": trend_values,
        "top_forms": top_forms,
        "spam_stats": spam_stats,
        "recent_submissions": recent_submissions,
        "failed_submissions": failed_submissions,
    }


@dash_router.get("/", response_class=HTMLResponse)
async def home(
    request: Request,
    user: User | None = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if not user:
        return temp.TemplateResponse(request, "index.html")

    summary = await _get_dashboard_summary(db, user)
    return temp.TemplateResponse(
        request,
        "dashboard.html",
        {
            "email": user.email,
            "name": user.name,
            "user_id": user.id,
            "page": "dashboard",
            **summary,
        },
    )
