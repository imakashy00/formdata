# auth/cookies.py
from fastapi import Response
from app.core.settings import settings


def _cookie_kwargs() -> dict:
    # SameSite=None requires Secure; use Lax on localhost (http)
    secure = settings.SECURE_COOKIES
    samesite = "none" if secure else "lax"
    return {
        "httponly": True,
        "secure": secure,
        "samesite": samesite,
        "domain": settings.COOKIE_DOMAIN,  # None on localhost, host in prod
        "path": "/",
    }


def set_auth_cookies(resp: Response, access: str, refresh: str):
    opts = _cookie_kwargs()
    resp.set_cookie(
        "access_token", access, max_age=int(settings.ACCESS_TTL.total_seconds()), **opts
    )
    resp.set_cookie(
        "refresh_token",
        refresh,
        max_age=int(settings.REFRESH_TTL.total_seconds()),
        **opts,
    )


def clear_auth_cookies(resp: Response):
    for name in ("access_token", "refresh_token"):
        resp.delete_cookie(name, domain=settings.COOKIE_DOMAIN, path="/")
