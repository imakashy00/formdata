import io
import re
from datetime import UTC, datetime, timedelta
from uuid import UUID

import httpx
from fastapi import HTTPException, Request
from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import IncorrectCloudflareTournstileKey
from app.core.settings import settings
from app.models.user import Form as FormDB
from app.models.user import Project, Submission, SubmissionStatus, User
from app.schemas.form import TAB_LABELS, TAB_TEMPLATES, FormSettingsPayload, FormTab

DISPOSABLE_EMAIL_DOMAINS = {
    "mailinator.com",
    "tempmail.com",
    "guerrillamail.com",
    "10minutemail.com",
    "yopmail.com",
    "trashmail.com",
}  # illustrative only — use a maintained list/service in production

SPAM_PATTERNS = [
    (re.compile(r"\b(viagra|cialis|casino|crypto\s*airdrop)\b", re.IGNORECASE), 3),
    (re.compile(r"\bmake\s+money\s+fast\b", re.IGNORECASE), 3),
    (re.compile(r"https?://\S+"), 1),  # scored per URL, see content_score()
]


# async def check_rate_limit(scope: str, key: str, limit: int, window_s: int) -> bool:
#     """Returns True if the request is within limit."""
#     redis_key = f"rl:{scope}:{key}:{int(time.time()) // window_s}"
#     count = await r.incr(redis_key)
#     if count == 1:
#         await r.expire(redis_key, window_s)
#     return count <= limit


async def verify_turnstile(
    token: str,
    secret: str,
    remote_ip: str | None,
):
    url = "https://challenges.cloudflare.com/turnstile/v0/siteverify"

    data = {"secret": secret, "response": token}
    if remote_ip:
        data["remoteip"] = remote_ip

    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(url, data=data, timeout=5.0)
            response.raise_for_status()
            result = response.json()

            if response.status_code != 200:
                return False, f"cloudflare_api_error_{response.status_code}"

            if result.get("success"):
                return True, None

            errors = result.get("error-codes", ["unknown_verification_failure"])
            return False, f"codes: {errors}"

    except httpx.HTTPStatusError as exc:
        # Captures raise_for_status style issues safely
        return False, f"http_status_exception: {exc!s}"
    except httpx.RequestError as exc:
        # Captures timeouts and network dropouts cleanly
        return False, f"network_exception: {exc!s}"


async def verify_bot_check(
    form_data: dict,
    request: Request,
    secret_key: str | None = "None",
):

    token = form_data.get("cf-turnstile-response")
    if not token:
        return False, "missing turnstile token"
    remoteip = request.headers.get("CF-Connecting-IP") or request.headers.get(
        "X-Forwarded-For"
    )

    if not secret_key:
        return False, "missing turnstile secret"

    return await verify_turnstile(token, secret_key, remoteip)


def check_user_agent(request: Request) -> bool:
    ua = request.headers.get("user-agent", "")
    return len(ua.strip()) > 0


def check_honeypot(form_data: dict, field_name: str | None = None) -> bool:
    """True if clean (honeypot empty)."""
    honeypot_field = field_name or settings.HONEYPOT_FIELD
    return not form_data.get(honeypot_field)


async def _count_submissions(
    db: AsyncSession,
    form_id: UUID,
    start: datetime | None = None,
    end: datetime | None = None,
    status: str | None = None,
) -> int:
    query = select(func.count(Submission.id)).where(Submission.form_id == form_id)
    if start is not None:
        query = query.where(Submission.created_at >= start)
    if end is not None:
        query = query.where(Submission.created_at < end)
    if status is not None:
        query = query.where(Submission.status == status)
    return await db.scalar(query) or 0


def _pct_change(current: int, previous: int) -> dict:
    """Handles the zero-previous-period case instead of dividing by zero,
    which a brand-new form would hit immediately."""
    if previous == 0:
        if current == 0:
            return {"direction": "flat", "value": 0, "label": "No change"}
        return {"direction": "up", "value": None, "label": "New activity"}
    delta = ((current - previous) / previous) * 100
    return {
        "direction": "up" if delta >= 0 else "down",
        "value": round(abs(delta), 1),
        "label": None,
    }


async def _get_form_analytics(
    db: AsyncSession, form: FormDB, range_days: int = 7
) -> dict:
    now = datetime.now(UTC)
    period_start = now - timedelta(days=range_days)
    prev_period_start = now - timedelta(days=range_days * 2)

    # Lifetime totals (not scoped to the selected range)
    total_submissions = await _count_submissions(db, form.id)

    # This-period vs previous-period volume
    submissions_this_period = await _count_submissions(db, form.id, start=period_start)
    submissions_prev_period = await _count_submissions(
        db, form.id, start=prev_period_start, end=period_start
    )
    submissions_change = _pct_change(submissions_this_period, submissions_prev_period)

    # Spam blocked in the selected range, broken down by provider
    spam_blocked = await _count_submissions(
        db, form.id, start=period_start, status="rejected"
    )
    rejected_prev_period = await _count_submissions(
        db, form.id, start=prev_period_start, end=period_start, status="rejected"
    )

    spam_provider_query = await db.execute(
        select(func.count(Submission.id))
        .where(Submission.form_id == form.id)
        .where(Submission.status == "rejected")
        .where(Submission.created_at >= period_start)
    )
    spam_by_provider = {
        str(row[0] or "other"): int(row[1]) for row in spam_provider_query.all()
    }

    # ------------------------------------------------------------------
    # Conversion rate = accepted / (accepted + rejected) for the period.
    # NOTE: proxy metric only — there's no impression/pageview tracking,
    # so this can't reflect true visit-to-submit conversion yet. It's
    # really "% of incoming traffic that passed spam filtering."
    # ------------------------------------------------------------------
    def _conversion_rate(accepted: int, rejected: int) -> float | None:
        total = accepted + rejected
        return round((accepted / total) * 100, 1) if total else None

    accepted_this_period = submissions_this_period - spam_blocked
    accepted_prev_period = submissions_prev_period - rejected_prev_period

    conversion_rate = _conversion_rate(accepted_this_period, spam_blocked)
    conversion_rate_prev = _conversion_rate(accepted_prev_period, rejected_prev_period)
    conversion_change = (
        round(conversion_rate - conversion_rate_prev, 1)
        if conversion_rate is not None and conversion_rate_prev is not None
        else None
    )

    # Daily trend for the bar chart, scoped to this form only
    trend = []
    for i in reversed(range(range_days)):
        day_date = (now - timedelta(days=i)).date()
        day_start = datetime.combine(day_date, datetime.min.time(), tzinfo=UTC)
        day_end = day_start + timedelta(days=1)
        count = await _count_submissions(db, form.id, start=day_start, end=day_end)
        trend.append(
            {
                "label": day_date.strftime("%a"),
                "date": day_date.strftime("%b %d"),
                "count": count,
            }
        )

    max_count = max((d["count"] for d in trend), default=0)
    for d in trend:
        d["height_pct"] = round((d["count"] / max_count) * 100, 1) if max_count else 0

    return {
        "total_submissions": total_submissions,
        "submissions_change": submissions_change,
        "spam_blocked": spam_blocked,
        "spam_by_provider": spam_by_provider,
        "conversion_rate": conversion_rate,
        "conversion_change": conversion_change,
        "trend": trend,
        "range_days": range_days,
    }


def _none_if_blank(value: str | None) -> str | None:
    """Turn an empty/whitespace-only string into None so optional columns
    stay NULL instead of storing "" when a settings toggle is switched off."""
    if value is None:
        return None
    value = value.strip()
    return value or None


async def update_form_settings(
    payload: FormSettingsPayload, db_form: FormDB, db: AsyncSession
):
    # 1. Parse comma-separated allowed domains into a list.
    accepted_domains_raw = payload.allowed_domains
    accepted_domains_list = [
        d.strip() for d in accepted_domains_raw.split(",") if d.strip()
    ]

    # 2. Key Length Validation (Leave this payload safety valve here)
    if (
        payload.turnstile_enabled
        and payload.turnstile_secret
        and len(payload.turnstile_secret) != 40
    ):
        raise IncorrectCloudflareTournstileKey()

    # 3. Apply Clean Payload Parameters directly to your SQLAlchemy Model instance
    db_form.name = payload.name.strip()
    db_form.honeypot = payload.honeypot
    db_form.notification_email = payload.notification_email
    db_form.allowed_domains = accepted_domains_list

    # Feature Toggle Column Assignments
    db_form.redirect = payload.redirect
    db_form.redirect_url = payload.redirect_url

    db_form.turnstile_enabled = payload.turnstile_enabled
    db_form.turnstile_secret = payload.turnstile_secret

    db_form.duplicate_allowed = payload.duplicate_allowed
    db_form.duplicate_check_input = payload.duplicate_check_input

    # Style and Visibility Settings
    db_form.is_active = payload.is_active
    db_form.sub_message = payload.sub_message
    db_form.sub_bg_color = payload.sub_bg_color
    db_form.sub_txt_color = payload.sub_txt_color
    db_form.sub_lnk_color = payload.sub_lnk_color

    # 4. Save Changes to PostgreSQL
    await db.commit()
    await db.refresh(db_form)


async def _get_owned_form(db: AsyncSession, user: User, form_id: str) -> FormDB:
    form = await db.scalar(
        select(FormDB)
        .join(Project, FormDB.project_id == Project.id)
        .where(FormDB.id == form_id, Project.user_id == user.id)
    )
    if not form:
        # 🟢 Don't leak existence of forms belonging to other users — 404, not 403
        raise HTTPException(status_code=404, detail="Form not found")
    return form


async def get_form_analytics(
    request: Request,
    form: FormDB,
    db: AsyncSession,
    user: User,
    search: str | None,
    status: str | None,
    form_id: str,
):
    # --- START ANALYTICS CALCULATION ---
    # Matches your model's UTC structure
    time_24h_ago = datetime.now(UTC) - timedelta(hours=24)

    stats_query = (
        select(
            # 1. Total Submissions for this form
            func.count(Submission.id).label("total"),
            # 2. Submissions in the last 24 hours
            func.count(Submission.id)
            .filter(Submission.created_at >= time_24h_ago)
            .label("last_24h"),
            # 3. Unread submissions (where opened is False)
            func.count(Submission.id)
            .filter(Submission.opened == False)
            .label("unread"),
            # 4. Spam submissions (where status is REJECTED)
            func.count(Submission.id)
            .filter(Submission.status == SubmissionStatus.REJECTED)
            .label("spam"),
        ).where(
            Submission.form_id == form_id
        )  # Filters data down to your specific form target
    )

    # Execute the query block
    result = await db.execute(stats_query)
    stats = result.mappings().one()

    stats = {
        "total": stats.total,
        "last_24h": stats.last_24h,
        "unread": stats.unread,
        "spam": stats.spam,
    }
    # --- END ANALYTICS CALCULATION ---

    # Build dynamic query for submissions matching this form
    submission_query = (
        select(Submission)
        .where(Submission.form_id == form_id)
        .order_by(desc(Submission.created_at))
    )

    # Apply backend filtering for Status
    if status:
        submission_query = submission_query.where(Submission.status == status)

    # Apply backend filtering for JSONB Search (checks common keys like email, name)
    if search:
        search_pattern = f"%{search}%"
        submission_query = submission_query.where(
            (Submission.payload["email"].astext.ilike(search_pattern))
            | (Submission.payload["name"].astext.ilike(search_pattern))
        )

    # Execute submission filter query
    submissions_result = await db.execute(submission_query)
    submissions = submissions_result.scalars().all()

    context = {
        "request": request,
        "form": form,
        "submissions": submissions,
        "search": search or "",
        "status": status or "",
        "stats": stats,
        "active_tab": "submissions",
        "active_tab_template": TAB_TEMPLATES[FormTab.submissions],
        "tab_labels": TAB_LABELS,
        "user": user,
        "page": "projects",
    }
    return context


async def generate_workbook_sheet(submissions: list[Submission], ws, wb):
    # We look at the first record's payload dictionary keys to create dynamic columns
    sample_payload = submissions[0].payload or {}
    dynamic_keys = list(sample_payload.keys())

    # Combine standard fixed model columns + your custom dynamic JSON keys
    base_headers = ["ID", "Status", "Opened", "Country", "Note", "Created At"]
    ws.append(base_headers + dynamic_keys)

    # 5. Populate Rows
    for sub in submissions:
        # Flatten fixed model row data values
        row_data = [
            str(sub.id),
            sub.status.value if hasattr(sub.status, "value") else str(sub.status),
            "Yes" if sub.opened else "No",
            sub.country or "Unknown",
            sub.note or "",
            sub.created_at.strftime("%Y-%m-%d %H:%M:%S %Z") if sub.created_at else "",
        ]

        # Safely extract matching JSONB payload fields for this row
        payload_data = sub.payload or {}
        for key in dynamic_keys:
            row_data.append(payload_data.get(key, ""))

        ws.append(row_data)

    # 6. Stream file binary payload directly to Alpine's fetch method without reloading page
    output = io.BytesIO()
    wb.save(output)
    output.seek(0)
    return output
