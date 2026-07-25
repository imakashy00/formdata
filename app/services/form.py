from datetime import datetime, timedelta, timezone
import hashlib
import hmac
import re
import secrets
import time
import uuid
from typing import Literal
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

import httpx
from altcha import (
    Challenge,
    create_challenge,
    verify_solution,
)
from fastapi import Request

from app.models.user import CaptchaType, Form as FormDB, Submission
from app.core.settings import settings
from app.schemas.form import FormSettingsPayload
from app.services.blacklist import redis_client as r

DISPOSABLE_EMAIL_DOMAINS = {
    "mailinator.com",
    "tempmail.com",
    "guerrillamail.com",
    "10minutemail.com",
    "yopmail.com",
    "trashmail.com",
}  # illustrative only — use a maintained list/service in production

SPAM_PATTERNS = [
    (re.compile(r"\b(viagra|cialis|casino|crypto\s*airdrop)\b", re.I), 3),
    (re.compile(r"\bmake\s+money\s+fast\b", re.I), 3),
    (re.compile(r"https?://\S+"), 1),  # scored per URL, see content_score()
]

# In-memory stand-in for your forms table.
FORMS: dict[str, dict] = {
    "frm_demo1": {
        "allowed_origins": {"https://customer-one.example.com"},
        "bot_provider": "altcha",  # default
        "turnstile_sitekey": None,
        "turnstile_secret": None,
        "fields": {"name", "email", "message"},
        "required": {"email", "message"},
    },
    "frm_demo2": {
        "allowed_origins": {"https://customer-two.example.com"},
        "bot_provider": "cloudflare_turnstile",  # this customer brought their own keys
        "turnstile_sitekey": "1x00000000000000000000AA",  # Cloudflare test sitekey
        "turnstile_secret": "1x0000000000000000000000000000000AA",  # Cloudflare test secret
        "fields": {"name", "email", "message"},
        "required": {"email", "message"},
    },
}


async def check_rate_limit(scope: str, key: str, limit: int, window_s: int) -> bool:
    """Returns True if the request is within limit."""
    redis_key = f"rl:{scope}:{key}:{int(time.time()) // window_s}"
    count = await r.incr(redis_key)
    if count == 1:
        await r.expire(redis_key, window_s)
    return count <= limit


def sign_session(form_id: str) -> str:
    issued_at = int(time.time())
    nonce = uuid.uuid4().hex
    msg = f"{form_id}:{issued_at}:{nonce}".encode()
    sig = hmac.new(
        settings.SESSION_SECRET.encode("utf-8"), msg, hashlib.sha256
    ).hexdigest()
    return f"{form_id}:{issued_at}:{nonce}:{sig}"


async def verify_session(token: str, form_id: str):
    try:
        fid, issued_at_s, nonce, sig = token.split(":")
    except ValueError:
        return False, "malformed session token"

    if fid != form_id:
        return False, "session token issued for a different form"

    msg = f"{fid}:{issued_at_s}:{nonce}".encode()
    expected = hmac.new(
        settings.SESSION_SECRET.encode("utf-8"), msg, hashlib.sha256
    ).hexdigest()
    if not hmac.compare_digest(sig, expected):
        return False, "session token signature invalid"

    issued_at = int(issued_at_s)
    age = time.time() - issued_at
    if age > settings.SESSION_TOKEN_MAX_AGE:
        return False, "session token expired"
    if age < settings.MIN_SUBMIT_SECONDS:
        return False, "submitted too fast for a human"

    # single-use, so a captured token can't be replayed
    first_use = await r.set(
        f"session_used:{nonce}", "1", nx=True, ex=settings.SESSION_TOKEN_MAX_AGE
    )
    if not first_use:
        return False, "session token already used"

    return True, None


def make_altcha_challenge() -> Challenge:
    challenge = create_challenge(
        algorithm="PBKDF2/SHA-256",
        cost=1000,
        counter=secrets.randbelow(5000) + 5000,
        hmac_secret=settings.ALTCHA_HMAC_SECRET,
        hmac_key_secret=settings.ALTCHA_HMAC_KEY_SECRET,
    )
    return challenge


async def verify_altcha(payload: str) -> tuple[bool, str | None]:
    result = verify_solution(payload, settings.ALTCHA_HMAC_SECRET)
    if not result.verified:
        return False, result.error or "altcha verification failed"
    # ALTCHA doesn't enforce single-use on its own — enforce it here.
    challenge_hash = hashlib.sha256(payload.encode()).hexdigest()
    first_use = await r.set(
        f"altcha_used:{challenge_hash}",
        "1",
        nx=True,
        ex=settings.ALTCHA_CHALLENGE_EXPIRES,
    )
    if not first_use:
        return False, "altcha solution already used"
    return True, None


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
        response = httpx.post(url, data=data)
        response.raise_for_status()
        result = response.json()

        if result.get("success"):
            return True, None

        return False, ", ".join(
            result.get("error-codes", [])
        ) or "turnstile verification failed"

    except httpx.RequestError as exc:
        # Catches network errors, timeouts, and transport issues
        print(f"An error occurred while requesting {exc.request.url!r}: {exc}")
        return False, "turnstile verification request failed"

    except httpx.HTTPStatusError as exc:
        # Catches 4xx and 5xx responses if raise_for_status() is called
        print(
            f"Error response {exc.response.status_code} while requesting {exc.request.url!r}"
        )
        return False, "turnstile verification request failed"


async def verify_bot_check(
    form: dict, form_data: dict, request: Request, secret_key: str | None = None
):
    captcha_type = getattr(form, "captcha_type", None)
    captcha_value = getattr(captcha_type, "value", captcha_type)

    if captcha_value == "altcha" or form.get("bot_provider") == "altcha":
        payload = form_data.get("altcha")
        if not payload:
            return False, "missing altcha payload"
        return await verify_altcha(payload)

    if (
        captcha_value == "cloudflare_turnstile"
        or form.get("bot_provider") == "cloudflare_turnstile"
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

    return False, "no bot check provider configured"


def check_user_agent(request: Request) -> bool:
    ua = request.headers.get("user-agent", "")
    return len(ua.strip()) > 0


def check_honeypot(form_data: dict, field_name: str | None = None) -> bool:
    """True if clean (honeypot empty)."""
    honeypot_field = field_name or settings.HONEYPOT_FIELD
    return not form_data.get(honeypot_field)


async def content_score(
    form_id: str, form: dict, form_data: dict
) -> tuple[int, list[str]]:
    score = 0
    reasons = []

    # Only score the form's actual declared fields — sessionToken, altcha,
    # and cf-turnstile-response are pipeline plumbing, not user content, and
    # differ on every request even when the real content is identical.
    content_fields = form["fields"] - {"email"}
    text_fields = " ".join(str(form_data.get(k, "")) for k in content_fields)

    for pattern, weight in SPAM_PATTERNS:
        matches = pattern.findall(text_fields)
        if matches:
            score += weight * min(len(matches), 3)  # cap per-pattern contribution
            reasons.append(f"pattern:{pattern.pattern[:20]} x{len(matches)}")

    email = form_data.get("email", "")
    domain = email.split("@")[-1].lower() if "@" in email else ""
    if domain in DISPOSABLE_EMAIL_DOMAINS:
        score += 4
        reasons.append("disposable-email")

    dedupe_key = hashlib.sha256(f"{form_id}:{text_fields}".encode()).hexdigest()
    is_new = await r.set(f"dedupe:{dedupe_key}", "1", nx=True, ex=600)
    if not is_new:
        score += 5
        reasons.append("duplicate-submission")

    return score, reasons


def get_form_temp(form):
    return FORMS.get(form)


def route(score: int) -> Literal["accept", "queue", "reject"]:
    if score >= 8:
        return "reject"
    if score >= 3:
        return "queue"
    return "accept"


async def _count_submissions(
    db: AsyncSession,
    form_id: str,
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
    now = datetime.now(timezone.utc)
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
        select(Submission.spam_provider, func.count(Submission.id))
        .where(Submission.form_id == form.id)
        .where(Submission.status == "rejected")
        .where(Submission.created_at >= period_start)
        .group_by(Submission.spam_provider)
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
        day_start = datetime.combine(day_date, datetime.min.time(), tzinfo=timezone.utc)
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


def _build_form_context(form) -> dict:
    captcha_type = getattr(form, "captcha_type", None)
    captcha_value = getattr(captcha_type, "value", captcha_type) or form.get(
        "bot_provider", "cloudflare_turnstile"
    )

    honeypot_value = getattr(form, "honeypot", None) or form.get(
        "honeypot", settings.HONEYPOT_FIELD
    )

    if hasattr(form, "turnstile_sitekey"):
        turnstile_sitekey = form.turnstile_sitekey
        turnstile_secret = form.turnstile_secret
    else:
        turnstile_sitekey = form.get("turnstile_sitekey")
        turnstile_secret = form.get("turnstile_secret")

    return {
        "bot_provider": captcha_value,
        "honeypot": honeypot_value,
        "turnstile_sitekey": turnstile_sitekey,
        "turnstile_secret": turnstile_secret,
        "fields": {"name", "email", "message"},
        "required": {"name", "email", "message"},
    }


async def update_form_settings(
    payload: FormSettingsPayload, db_form: FormDB, db: AsyncSession
):
    accepted_domains_raw = payload.allowed_domains
    accepted_domains_list = [
        d.strip() for d in accepted_domains_raw.split(",") if d.strip()
    ]
    # 4. Update existing form fields with the payload data
    db_form.name = payload.name.strip()
    db_form.honeypot = payload.honeypot
    db_form.notification_email = payload.notification_email
    db_form.redirect_url = payload.redirect_url if payload.redirect_url else None
    db_form.allowed_domains = accepted_domains_list
    db_form.captcha_type = payload.captcha_type
    if payload.captcha_type == CaptchaType.TURNSTILE:
        db_form.turnstile_sitekey = payload.turnstile_sitekey
        db_form.turnstile_secret = payload.turnstile_secret
    else:
        db_form.turnstile_sitekey = None
        db_form.turnstile_secret = None
    db_form.is_active = payload.is_active
    db_form.sub_message = payload.sub_message
    db_form.sub_bg_color = payload.sub_bg_color
    db_form.sub_txt_color = payload.sub_txt_color
    db_form.sub_lnk_color = payload.sub_lnk_color

    # 5. Commit changes to database
    await db.commit()
    await db.refresh(db_form)
