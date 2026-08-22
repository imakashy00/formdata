from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from jinja2 import TemplateError
from loguru import logger as log
from pydantic import ValidationError as PydanticValidationError
from sqlalchemy.exc import SQLAlchemyError
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.responses import Response

from app.core.errors import AppError, ToastType
from app.core.htmx import hx_toast_headers, is_html_request, is_htmx
from app.core.settings import settings
from app.core.templates import temp


def _error_response(
    request: Request,
    status_code: int,
    message: str,
    toast_type: str,
    *,
    debug_detail=None,
):
    if is_htmx(request):
        # Real status code, not 200 — htmx skips swapping on 4xx/5xx by
        # default, which protects whatever's already in hx-target. Forcing
        # 200 here would make htmx treat this as success and swap the
        # empty body in, wiping the target's existing content.
        return Response(
            status_code=status_code, headers=hx_toast_headers(message, type_=toast_type)
        )

    if is_html_request(request):
        template = (
            "404.html" if status_code == status.HTTP_400_BAD_REQUEST else "500.html"
        )
        return temp.TemplateResponse(
            request,
            template,
            {"detail": message, "status_code": status_code},
            status_code=status_code,
        )

    content = {"detail": message, "status_code": status_code}
    if debug_detail is not None and settings.ENV != "production":
        content["debug"] = debug_detail
    return JSONResponse(status_code=status_code, content=content)


def register_exception_handlers(app: FastAPI) -> None:

    @app.exception_handler(AppError)
    async def app_error_handler(request: Request, exc: AppError):
        return _error_response(request, exc.status_code, exc.message, exc.toast_type)

    @app.exception_handler(RequestValidationError)
    async def validation_handler(request: Request, exc: RequestValidationError):
        log.warning(f"Validation error: {exc.errors()}")
        errors = exc.errors()
        is_uuid_error = any(
            "path" in err.get("loc", ()) and "uuid" in err.get("msg", "").lower()
            for err in errors
        )

        if is_uuid_error:
            if is_htmx(request):
                # HX-Redirect is only honored by htmx on a 200 response —
                # the one deliberate exception to "always use the real
                # status code" above. Because a redirect is about to
                # navigate away, there's no stale-swap risk here.
                return Response(
                    status_code=status.HTTP_200_OK,
                    headers=hx_toast_headers(
                        "Invalid project resource requested.",
                        type_="error",
                        redirect="/",
                    ),
                )
            return temp.TemplateResponse(
                request, "404.html", status_code=status.HTTP_404_NOT_FOUND
            )

        return _error_response(
            request,
            422,
            "Invalid submission data.",
            "warning",
            debug_detail={"errors": errors, "body": exc.body},
        )

    @app.exception_handler(PydanticValidationError)
    async def pydantic_validation_handler(
        request: Request, exc: PydanticValidationError
    ):
        msg = exc.errors()[0]["msg"].replace("Value error, ", "", 1)
        return _error_response(
            request, status.HTTP_400_BAD_REQUEST, msg, ToastType.ERROR
        )

    @app.exception_handler(StarletteHTTPException)
    async def http_exception_handler(request: Request, exc: StarletteHTTPException):
        if exc.status_code >= 500:
            log.error(f"HTTP {exc.status_code}: {exc.detail}", exc_info=True)
        message = exc.detail if isinstance(exc.detail, str) else "Request failed."
        toast_type = (
            "error"
            if exc.status_code >= status.HTTP_500_INTERNAL_SERVER_ERROR
            else "warning"
        )
        return _error_response(request, exc.status_code, message, toast_type)

    @app.exception_handler(SQLAlchemyError)
    async def db_exception_handler(request: Request, exc: SQLAlchemyError):
        log.critical(f"DB error at {request.url.path}: {exc}", exc_info=True)
        return _error_response(
            request,
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            "Something went wrong. Try again.",
            "error",
        )

    @app.exception_handler(TemplateError)
    async def template_exception_handler(request: Request, exc: TemplateError):
        log.critical(f"Jinja error at {request.url.path}: {exc}", exc_info=True)
        return _error_response(
            request,
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            "Unable to render page content. Contact support.",
            "error",
        )

    @app.exception_handler(Exception)
    async def generic_exception_handler(request: Request, exc: Exception):
        log.critical(f"Unhandled exception: {exc}", exc_info=True)
        message = (
            "An internal server error occurred."
            if settings.ENV == "production"
            else str(exc)
        )
        return _error_response(
            request,
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            message,
            "error",
            debug_detail=str(exc),
        )
