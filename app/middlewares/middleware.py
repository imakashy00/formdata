from jwt.exceptions import ExpiredSignatureError
from fastapi.responses import RedirectResponse
from loguru import logger as log
from fastapi import HTTPException, Request

from app.services.auth import AuthService
from app.services.cookies import clear_auth_cookies, set_auth_cookies


allowed_paths = {
    "/",
    "/ytnote.png",
    "/static/favicon.svg",
    "/robots.txt",
    "/help",
    "/auth",
    "/auth/callback",
    "/webhook/paddle",
}


def redirect_home():
    resp = RedirectResponse(url="/", status_code=302)
    clear_auth_cookies(resp)
    return resp


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
    async def protection_middleware(request: Request, call_next):
        if request.url.path in allowed_paths:
            return await call_next(request)

        request.state.user = None

        access_token = request.cookies.get("access_token")
        refresh_token = request.cookies.get("refresh_token")

        new_access = None
        new_refresh = None

        if access_token:
            log.debug("Access token found.")
            try:
                request.state.user = await AuthService.validate_access(access_token)
            except HTTPException as e:
                if e.detail != "access_expired":
                    log.debug(f"Access invalid: {e.detail}")
                    return redirect_home()

        if request.state.user is None and refresh_token:
            log.debug("Refresh token found")
            try:
                new_access, new_refresh = await AuthService.try_refresh(refresh_token)
                payload = AuthService.decode(new_access)
                request.state.user = payload
                log.debug("🔄 Refreshed tokens and retried request")
            except ExpiredSignatureError:
                log.debug("Refresh Token Expired")
                return redirect_home()
            except HTTPException as e:
                log.debug(f"Refresh failed: {e.detail}")
                return redirect_home()
            except Exception as e:
                log.error(f"❌ Unexpected error during refresh: {e}")
                return redirect_home()

        if request.state.user is None:
            return redirect_home()

        response = await call_next(request)

        if new_access and new_refresh:
            set_auth_cookies(response, new_access, new_refresh)
            log.debug("🍪 Updated cookies sent to client.")

        return response
