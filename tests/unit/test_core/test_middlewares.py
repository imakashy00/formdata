import pytest
from fastapi import FastAPI, HTTPException
from fastapi.exceptions import RequestValidationError
from httpx import ASGITransport, AsyncClient
from starlette.requests import Request
from starlette.responses import JSONResponse

from app.core.errors import AppException, NotFoundError, UnauthorizedError
from app.core.middlewares.exception_handlers import (
    app_exception_handler,
    generic_exception_handler,
    http_exception_handler,
    validation_exception_handler,
)


@pytest.mark.asyncio
async def test_app_exception_handler_json():
    """Verify app_exception_handler returns formatted JSON response for API requests."""
    test_app = FastAPI()
    test_app.add_exception_handler(AppException, app_exception_handler)

    @test_app.get("/trigger-error")
    async def trigger_error():
        raise NotFoundError(message="Custom resource missing", details={"id": "xyz"})

    transport = ASGITransport(app=test_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/trigger-error", headers={"accept": "application/json"})
        assert response.status_code == 404
        data = response.json()
        assert data.get("error") == "Custom resource missing" or "details" in data


@pytest.mark.asyncio
async def test_http_exception_handler():
    """Verify standard HTTPException handler returns clean JSON or HTML response."""
    test_app = FastAPI()
    test_app.add_exception_handler(HTTPException, http_exception_handler)

    @test_app.get("/trigger-http-error")
    async def trigger_http():
        raise HTTPException(status_code=403, detail="Forbidden action")

    transport = ASGITransport(app=test_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/trigger-http-error", headers={"accept": "application/json"})
        assert response.status_code == 403


@pytest.mark.asyncio
async def test_generic_exception_handler():
    """Verify unhandled runtime exceptions are caught with a 500 error."""
    test_app = FastAPI()
    test_app.add_exception_handler(Exception, generic_exception_handler)

    @test_app.get("/trigger-unhandled")
    async def trigger_unhandled():
        raise RuntimeError("Unexpected server crash")

    transport = ASGITransport(app=test_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/trigger-unhandled", headers={"accept": "application/json"})
        assert response.status_code == 500
