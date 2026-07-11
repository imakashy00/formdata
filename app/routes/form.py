import secrets

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

import hmac
import hashlib
import time

import re
import uuid
from typing import Literal

from altcha import (
    Challenge,
    create_challenge,
    verify_solution,
)
import httpx
import redis.asyncio as redis

from fastapi.responses import JSONResponse


from app.core.templates import temp

form_router = APIRouter()


SESSION_SECRET = b"replace-with-a-real-32-byte-secret-loaded-from-env"
ALTCHA_HMAC_SECRET = "a332ecef37a92492dd43a5e1696a4f7ef1615503a7fda46a93a7ef24458f2489"
ALTCHA_HMAC_KEY_SECRET = (
    "9dfb931ec4f297f1b07b4dbb698ebb6e41018ae9b1de2f0bbd656968a4d1e8e3"
)


MIN_SUBMIT_SECONDS = 1.5  # reject submissions faster than a human could type
SESSION_TOKEN_MAX_AGE = 60 * 30  # sessions older than this are stale, not just "fast"
ALTCHA_CHALLENGE_EXPIRES = 120  # seconds a challenge stays valid

RATE_LIMIT_IP = (20, 60)  # 20 requests / 60s per IP across all forms
RATE_LIMIT_FORM = (200, 60)  # 200 requests / 60s per form, isolates noisy tenants

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
        "bot_provider": "turnstile",  # this customer brought their own keys
        "turnstile_sitekey": "1x00000000000000000000AA",  # Cloudflare test sitekey
        "turnstile_secret": "1x0000000000000000000000000000000AA",  # Cloudflare test secret
        "fields": {"name", "email", "message"},
        "required": {"email", "message"},
    },
}
HONEYPOT_FIELD = "_hp"

r = redis.Redis(host="localhost", port=6379, decode_responses=True)


class WidgetConfig(BaseModel):
    provider: str

    honeypotField: str

    sessionToken: str

    challengeUrl: str

    success: dict | None = None


def get_form(form_id: str) -> dict | None:
    return FORMS.get(form_id)


# ---------------------------------------------------------------------------
# 2. Rate limiting (Redis fixed window — swap for a sliding window at scale)
# ---------------------------------------------------------------------------


async def check_rate_limit(scope: str, key: str, limit: int, window_s: int) -> bool:
    """Returns True if the request is within limit."""
    redis_key = f"rl:{scope}:{key}:{int(time.time()) // window_s}"
    count = await r.incr(redis_key)
    if count == 1:
        await r.expire(redis_key, window_s)
    return count <= limit


# ---------------------------------------------------------------------------
# 3-4. Fast structural checks: UA, honeypot, timing (via a signed session token)
# ---------------------------------------------------------------------------


def sign_session(form_id: str) -> str:
    issued_at = int(time.time())
    nonce = uuid.uuid4().hex
    msg = f"{form_id}:{issued_at}:{nonce}".encode()
    sig = hmac.new(SESSION_SECRET, msg, hashlib.sha256).hexdigest()
    return f"{form_id}:{issued_at}:{nonce}:{sig}"


async def verify_session(token: str, form_id: str):
    try:
        fid, issued_at_s, nonce, sig = token.split(":")
    except ValueError:
        return False, "malformed session token"

    if fid != form_id:
        return False, "session token issued for a different form"

    msg = f"{fid}:{issued_at_s}:{nonce}".encode()
    expected = hmac.new(SESSION_SECRET, msg, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(sig, expected):
        return False, "session token signature invalid"

    issued_at = int(issued_at_s)
    age = time.time() - issued_at
    if age > SESSION_TOKEN_MAX_AGE:
        return False, "session token expired"
    if age < MIN_SUBMIT_SECONDS:
        return False, "submitted too fast for a human"

    # single-use, so a captured token can't be replayed
    first_use = await r.set(
        f"session_used:{nonce}", "1", nx=True, ex=SESSION_TOKEN_MAX_AGE
    )
    if not first_use:
        return False, "session token already used"

    return True, None


def make_altcha_challenge() -> Challenge:
    challenge = create_challenge(
        algorithm="PBKDF2/SHA-256",
        cost=1000,
        counter=secrets.randbelow(5000) + 5000,
        hmac_secret=ALTCHA_HMAC_SECRET,
        hmac_key_secret=ALTCHA_HMAC_KEY_SECRET,
    )
    return challenge


async def verify_altcha(payload: str) -> tuple[bool, str | None]:
    result = verify_solution(payload, ALTCHA_HMAC_SECRET)
    if not result.verified:
        return False, result.error or "altcha verification failed"
    # ALTCHA doesn't enforce single-use on its own — enforce it here.
    challenge_hash = hashlib.sha256(payload.encode()).hexdigest()
    first_use = await r.set(
        f"altcha_used:{challenge_hash}", "1", nx=True, ex=ALTCHA_CHALLENGE_EXPIRES
    )
    if not first_use:
        return False, "altcha solution already used"
    return True, None


async def verify_turnstile(
    token: str, secret: str, remote_ip: str, expected_hostname: str | None
) -> tuple[bool, str | None]:
    async with httpx.AsyncClient(timeout=5.0) as client:
        resp = await client.post(
            "https://challenges.cloudflare.com/turnstile/v0/siteverify",
            json={"secret": secret, "response": token, "remoteip": remote_ip},
        )
    result = resp.json()
    if not result.get("success"):
        return False, ",".join(
            result.get("error-codes", ["turnstile verification failed"])
        )
    if expected_hostname and result.get("hostname") != expected_hostname:
        return False, "turnstile hostname mismatch"
    return True, None


async def verify_bot_check(
    form: dict, form_data: dict, request: Request
) -> tuple[bool, str | None]:
    if form["bot_provider"] == "altcha":
        payload = form_data.get("altcha")
        if not payload:
            return False, "missing altcha payload"
        return await verify_altcha(payload)

    if form["bot_provider"] == "turnstile":
        token = form_data.get("cf-turnstile-response")
        if not token:
            return False, "missing turnstile token"
        origin = request.headers.get("origin", "")
        hostname = origin.replace("https://", "").replace("http://", "")
        return await verify_turnstile(
            token,
            form["turnstile_secret"],
            request.client.host if request.client else "unknown",
            hostname,
        )

    return False, "no bot check provider configured"


def check_user_agent(request: Request) -> bool:
    ua = request.headers.get("user-agent", "")
    return len(ua.strip()) > 0


def check_honeypot(form_data: dict) -> bool:
    """True if clean (honeypot empty)."""
    return not form_data.get(HONEYPOT_FIELD)


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


def route(score: int) -> Literal["accept", "queue", "reject"]:
    if score >= 8:
        return "reject"
    if score >= 3:
        return "queue"
    return "accept"


@form_router.get("/test-widget", response_class=HTMLResponse)
async def test_widget(request: Request):
    return temp.TemplateResponse(request, "test.html", {"request": request})


@form_router.get("/form/{formId}/config", response_model=WidgetConfig)
async def return_form_config(request: Request, formId: str):
    print(formId)
    # form = get_form(form_id=formId)
    if not formId:
        return JSONResponse({"error": "unknown form"}, status_code=404)

    token = "sdkjfslfjsdlkfjsdlkfjsdlkfjlsdkfjlsdjf"
    config = WidgetConfig(
        provider="altcha",
        honeypotField="website",
        sessionToken=token,
        challengeUrl=f"http://localhost:8000/form/{formId}/altcha-challenge",
        success={
            "message": "Thanks! Your message has been sent successfully.",
            "redirect": None,  # Keep them on the same page
        },
    )
    # if form["bot_provider"] == "altcha":
    #         config.challengeUrl = f"http://localhost:8000/form/{formId}/altcha-challenge"
    #     elif form["bot_provider"] == "turnstile":
    #         config.turnstileSitekey = form["turnstile_sitekey"]

    return config


class AltchaChallenge(BaseModel):
    algorithm: str
    cost: int
    keyLength: int = Field(..., alias="keyLength")
    keyPrefix: str = Field(..., alias="keyPrefix")
    nonce: str
    salt: str
    keySignature: str | None

    class Config:
        # This allows you to create the model using camelCase or snake_case
        populate_by_name = True


@form_router.get("/form/{form_id}/altcha-challenge")
async def altcha_challenge(request: Request, form_id: str):
    form = get_form(form_id)
    if not form or form["bot_provider"] != "altcha":
        return JSONResponse(
            {"error": "altcha not enabled for this form"}, status_code=404
        )
    return make_altcha_challenge().to_dict()


@form_router.post("/form/{form_id}/submit")
async def submit(form_id: str, request: Request):
    form = get_form(form_id)
    if not form:
        return JSONResponse({"error": "unknown form"}, status_code=404)

    # --- edge-equivalent: rate limiting ---
    ip = request.client.host if request.client else "unknown"
    if not await check_rate_limit("ip", ip, *RATE_LIMIT_IP):
        return JSONResponse({"error": "rate limit exceeded"}, status_code=429)
    if not await check_rate_limit("form", form_id, *RATE_LIMIT_FORM):
        return JSONResponse(
            {"error": "form is receiving too many submissions"}, status_code=429
        )

    # --- fast structural checks ---
    if not check_user_agent(request):
        return JSONResponse({"error": "missing user agent"}, status_code=400)

    form_data = dict(await request.form())

    if not check_honeypot(form_data):
        # Bots that fill every field trip this. Respond as if successful —
        # no need to teach the bot what tripped it.
        return JSONResponse({"status": "accepted"}, status_code=200)

    missing = form["required"] - form_data.keys()
    if missing:
        return JSONResponse(
            {"error": f"missing fields: {sorted(missing)}"}, status_code=400
        )
    token_value = form_data.get("sessionToken", "")

    if not isinstance(token_value, str):
        session_ok, session_err = False, "invalid session token format"
    else:
        session_ok, session_err = await verify_session(token_value, form_id)
    if not session_ok:
        return JSONResponse({"error": session_err}, status_code=400)

    # --- bot verification (ALTCHA by default, or the customer's Turnstile) ---
    bot_ok, bot_err = await verify_bot_check(form, form_data, request)
    if not bot_ok:
        return JSONResponse({"error": f"bot check failed: {bot_err}"}, status_code=400)

    # --- content filter (scored, not hard-reject) ---
    score, reasons = await content_score(form_id, form, form_data)
    decision = route(score)

    if decision == "reject":
        return JSONResponse({"status": "rejected", "reasons": reasons}, status_code=200)

    return JSONResponse({"status": decision}, status_code=200)
