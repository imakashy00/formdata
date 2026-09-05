from datetime import UTC, datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.core.templates import temp
from app.models.user import Form as FormDB
from app.models.user import Project, Submission, Subscription, User
from app.services.account import (
    calculate_submission_quota,
    get_monthly_submission_usage,
    get_plan_limits,
)
from app.services.dependencies import current_user

dash_router = APIRouter()


async def _get_metrics(db: AsyncSession, user_id) -> dict:
    cutoff_24h = datetime.now(UTC) - timedelta(hours=24)
    projects_count = await db.scalar(
        select(func.count(Project.id)).where(Project.user_id == user_id)
    )
    forms_query = await db.execute(
        select(FormDB.is_active, func.count(FormDB.id))
        .select_from(FormDB)
        .join(Project, FormDB.project_id == Project.id)
        .where(Project.user_id == user_id)
        .group_by(FormDB.is_active)
    )
    forms_status = {is_active: count for is_active, count in forms_query.all()}
    submission_base = (
        select(func.count(Submission.id))
        .select_from(Submission)
        .join(FormDB, Submission.form_id == FormDB.id)
        .join(Project, FormDB.project_id == Project.id)
        .where(Project.user_id == user_id)
    )
    submissions_count = await db.scalar(submission_base)
    submissions_last_24h = await db.scalar(
        submission_base.where(Submission.created_at >= cutoff_24h)
    )
    active_forms = forms_status.get(True, 0)
    paused_forms = forms_status.get(False, 0)
    return {
        "projects_count": projects_count or 0,
        "forms_count": active_forms + paused_forms,
        "active_forms": active_forms,
        "paused_forms": paused_forms,
        "submissions_count": submissions_count or 0,
        "submissions_last_24h": submissions_last_24h or 0,
    }


async def _get_quota(db: AsyncSession, user_id) -> dict:
    subscription = await db.scalar(
        select(Subscription).where(Subscription.user_id == user_id)
    )
    plan_limit = get_plan_limits(subscription)["submissions"]
    # Paid plans use their billing allowance. Keep the current 5,000-unit
    # allowance for customers without a paid subscription.
    quota_limit = plan_limit or 5000
    if subscription:
        quota_usage = subscription.submissions_used
    else:
        month_start = datetime.now(UTC).replace(
            day=1, hour=0, minute=0, second=0, microsecond=0
        )
        quota_usage = await get_monthly_submission_usage(db, user_id, month_start)
    return {"submission_quota": calculate_submission_quota(quota_usage, quota_limit)}


async def _get_trend(db: AsyncSession, user_id) -> dict:
    now = datetime.now(UTC)
    labels: list[str] = []
    values: list[int] = []
    for offset in reversed(range(7)):
        day = (now - timedelta(days=offset)).date()
        day_start = datetime.combine(day, datetime.min.time(), tzinfo=UTC)
        day_end = datetime.combine(day, datetime.max.time(), tzinfo=UTC)
        count = await db.scalar(
            select(func.count(Submission.id))
            .select_from(Submission)
            .join(FormDB, Submission.form_id == FormDB.id)
            .join(Project, FormDB.project_id == Project.id)
            .where(Project.user_id == user_id)
            .where(Submission.created_at.between(day_start, day_end))
        )
        labels.append(day.strftime("%b %d"))
        values.append(count or 0)

    # Server-rendered SVG requires neither an external chart library nor an
    # inline script, so it remains compatible with a strict CSP.
    width, height, left, right, top, bottom = 640, 220, 28, 14, 18, 36
    plot_width = width - left - right
    plot_height = height - top - bottom
    maximum = max(values) or 1
    step = plot_width / max(len(values) - 1, 1)
    points = []
    for index, (label, value) in enumerate(zip(labels, values, strict=True)):
        x = round(left + index * step, 2)
        y = round(top + plot_height - (value / maximum * plot_height), 2)
        points.append({"x": x, "y": y, "label": label, "value": value})

    line_points = " ".join(f"{point['x']},{point['y']}" for point in points)
    area_path = ""
    if points:
        line_commands = " ".join(f"L {point['x']} {point['y']}" for point in points)
        area_path = (
            f"M {points[0]['x']} {top + plot_height} {line_commands} "
            f"L {points[-1]['x']} {top + plot_height} Z"
        )
    return {
        "trend_points": points,
        "trend_line_points": line_points,
        "trend_area_path": area_path,
        "trend_baseline": top + plot_height,
    }


async def _get_top_forms(db: AsyncSession, user_id) -> dict:
    count_expr = func.count(Submission.id)
    result = await db.execute(
        select(FormDB.id, FormDB.name, count_expr.label("submission_count"))
        .join(Submission, Submission.form_id == FormDB.id)
        .join(Project, FormDB.project_id == Project.id)
        .where(Project.user_id == user_id)
        .group_by(FormDB.id, FormDB.name)
        .order_by(count_expr.desc())
        .limit(5)
    )
    return {
        "top_forms": [
            {"id": row.id, "name": row.name, "count": row.submission_count}
            for row in result.all()
        ]
    }


async def _get_recent_submissions(db: AsyncSession, user_id) -> dict:
    result = await db.execute(
        select(Submission.created_at, FormDB.name.label("form_name"))
        .join(FormDB, Submission.form_id == FormDB.id)
        .join(Project, FormDB.project_id == Project.id)
        .where(Project.user_id == user_id)
        .where(Submission.status == "accepted")
        .order_by(Submission.created_at.desc())
        .limit(5)
    )
    return {
        "recent_submissions": [
            {
                "form_name": row.form_name,
                "created_at": row.created_at.strftime("%b %-d, %H:%M"),
            }
            for row in result.all()
        ]
    }


async def _get_dashboard_summary(db: AsyncSession, user: User) -> dict:
    metrics = await _get_metrics(db, user.id)
    quota = await _get_quota(db, user.id)
    trend = await _get_trend(db, user.id)
    top_forms = await _get_top_forms(db, user.id)
    recent_submissions = await _get_recent_submissions(db, user.id)
    return metrics | quota | trend | top_forms | recent_submissions


def _section_response(
    request: Request, template_name: str, context: dict
) -> HTMLResponse:
    return temp.TemplateResponse(request, template_name, context)


@dash_router.get("/dashboard/metrics", response_class=HTMLResponse)
async def dashboard_metrics(
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(current_user)],
):
    return _section_response(
        request, "partials/dashboard/metrics.html", await _get_metrics(db, user.id)
    )


@dash_router.get("/dashboard/quota", response_class=HTMLResponse)
async def dashboard_quota(
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(current_user)],
):
    return _section_response(
        request, "partials/dashboard/quota.html", await _get_quota(db, user.id)
    )


@dash_router.get("/dashboard/trend", response_class=HTMLResponse)
async def dashboard_trend(
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(current_user)],
):
    return _section_response(
        request, "partials/dashboard/trend.html", await _get_trend(db, user.id)
    )


@dash_router.get("/dashboard/top-forms", response_class=HTMLResponse)
async def dashboard_top_forms(
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(current_user)],
):
    return _section_response(
        request, "partials/dashboard/top_forms.html", await _get_top_forms(db, user.id)
    )


@dash_router.get("/dashboard/recent-submissions", response_class=HTMLResponse)
async def dashboard_recent_submissions(
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(current_user)],
):
    return _section_response(
        request,
        "partials/dashboard/recent_submissions.html",
        await _get_recent_submissions(db, user.id),
    )


@dash_router.get("/", response_class=HTMLResponse)
async def home(
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User | None, Depends(current_user)] = None,
):
    if not user:
        return temp.TemplateResponse(request, "index.html")
    summary = await _get_dashboard_summary(db, user)
    return temp.TemplateResponse(
        request,
        "dashboard.html",
        {"user": user, "page": "dashboard", **summary},
    )
