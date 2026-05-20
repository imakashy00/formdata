from fastapi import Request, status
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException
from loguru import logger as log
from app.core.settings import settings


async def generic_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """
    Handle all unhandled exceptions.
    In production: Return generic error message
    In development: Return detailed error information
    """
    # Log the full error server-side
    log.error(f"Unhandled exception: {exc}", exc_info=True)
    
    if settings.ENV == "production":
        # Production: Generic error message
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={
                "detail": "An internal server error occurred. Please try again later.",
                "status_code": 500,
            },
        )
    else:
        # Development: Detailed error information
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={
                "detail": str(exc),
                "type": type(exc).__name__,
                "status_code": 500,
            },
        )


async def http_exception_handler(request: Request, exc: StarletteHTTPException) -> JSONResponse:
    """
    Handle HTTP exceptions (4xx, 5xx errors)
    """
    # Log server errors (5xx)
    if exc.status_code >= 500:
        log.error(f"HTTP {exc.status_code}: {exc.detail}", exc_info=True)
    
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "detail": exc.detail,
            "status_code": exc.status_code,
        },
    )


async def validation_exception_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    """
    Handle request validation errors (422 Unprocessable Entity)
    """
    log.warning(f"Validation error: {exc.errors()}")
    
    if settings.ENV == "production":
        # Production: Simplified validation errors
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            content={
                "detail": "Invalid request data",
                "status_code": 422,
            },
        )
    else:
        # Development: Detailed validation errors
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            content={
                "detail": exc.errors(),
                "body": exc.body,
                "status_code": 422,
            },
        )


def register_exception_handlers(app):
    """Register all custom exception handlers"""
    app.add_exception_handler(Exception, generic_exception_handler)
    app.add_exception_handler(StarletteHTTPException, http_exception_handler)
    app.add_exception_handler(RequestValidationError, validation_exception_handler)
