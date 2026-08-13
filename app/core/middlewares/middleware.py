from fastapi import HTTPException, Request
from fastapi.responses import RedirectResponse
from jwt.exceptions import ExpiredSignatureError
from loguru import logger as log

from app.core.db import AsyncSessionLocal
from app.services.auth import decode, try_refresh, validate_access
from app.services.cookies import clear_auth_cookies, set_auth_cookies

PUBLIC_PREFIXES = ("/static", "/blogs")
PUBLIC_PATHS = {
    "/",
    "/help",
    "/auth",
    "/auth/callback",
    "/webhook/paddle",
    "/webhook/resend",
    "/privacy-policy",
    "/terms",
    "/robots.txt",
    "/sitemap.xml",
    "/favicon.ico",
}


def redirect_home():
    resp = RedirectResponse(url="/", status_code=302)
    clear_auth_cookies(resp)
    return resp


async def _handle_token_refresh(
    request: Request,
    refresh_token: str,
):
    """
    Refresh tokens using a SHORT-LIVED database session.
    The session exists only for the refresh-token DB operations.
    """

    try:
        # This prevents every normal request from holding a DB session.
        async with AsyncSessionLocal() as db:
            new_access, new_refresh = await try_refresh(
                db,
                refresh_token,
            )
        payload = decode(new_access)
        request.state.user = payload
        log.debug("🔄 Refreshed tokens and retried request")
        return new_access, new_refresh

    except ExpiredSignatureError:
        log.debug("Refresh token expired")
        return None, None

    except HTTPException as e:
        log.debug(f"Refresh failed: {e.detail}")
        return None, None

    except Exception as e:
        log.exception(f"❌ Unexpected error during refresh: {e}")
        return None, None


def register_middlewares(app):
    @app.middleware("http")
    async def log_requests(request: Request, call_next):
        log.info(f"⬇️ Req: {request.method} {request.url.path}")
        try:
            response = await call_next(request)
            log.info(f"⬆️ Res: {response.status_code} for {request.url.path}")
            return response
        except Exception as e:
            log.exception(f"🚫 Error processing request {request.url.path}: {e}")
            raise

    @app.middleware("http")
    async def protection_middleware(
        request: Request,
        call_next,
    ):
        if request.url.path.startswith("/static"):
            return await call_next(request)

        request.state.user = None

        access_token = request.cookies.get("access_token")
        refresh_token = request.cookies.get("refresh_token")

        new_access = None
        new_refresh = None

        if access_token:
            log.debug("Access token found.")
            try:
                payload = decode(access_token)
                if payload.get("type") != "access":
                    log.debug("Wrong token type.")
                    return redirect_home()

                async with AsyncSessionLocal() as db:
                    request.state.user = await validate_access(payload, db)
            except ExpiredSignatureError:
                if refresh_token:
                    log.debug("Access token expired, attempting refresh...")
                    new_access, new_refresh = await _handle_token_refresh(
                        request, refresh_token
                    )
                if not request.state.user:
                    return redirect_home()
            except HTTPException as e:
                log.debug(f"Access invalid for other reason: {e.detail}")
                return redirect_home()

        elif refresh_token:
            log.debug("No access token, but refresh token found")
            new_access, new_refresh = await _handle_token_refresh(
                request, refresh_token
            )
            if not request.state.user:
                return redirect_home()

        is_public = request.url.path in PUBLIC_PATHS or request.url.path.startswith(
            PUBLIC_PREFIXES
        )

        if request.state.user is None and not is_public:
            return redirect_home()

        response = await call_next(request)

        if new_access and new_refresh:
            set_auth_cookies(response, new_access, new_refresh)
            log.debug("🍪 Updated cookies sent to client.")

        return response
