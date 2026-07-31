# auth/cookies.py
from app.core.settings import settings
from fastapi import Response


def _cookie_kwargs() -> dict:
    # SameSite=None requires Secure; use Lax on localhost (http)
    secure = str(settings.SECURE_COOKIES)
    samesite = "none" if secure else "lax"
    return {
        "httponly": True,
        "secure": secure,
        "samesite": samesite,
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
        resp.delete_cookie(name, path="/")
