import pytest
from fastapi import FastAPI, HTTPException
from httpx import ASGITransport, AsyncClient

from app.core.errors import AppError, NotFoundError
from app.core.middlewares.exception_handlers import register_exception_handlers


@pytest.mark.asyncio
async def test_app_error_handler_json():
    """Verify app_error_handler returns formatted JSON response for API requests."""
    test_app = FastAPI()
    register_exception_handlers(test_app)

    @test_app.get("/trigger-error")
    async def trigger_error():
        raise NotFoundError(message="Custom resource missing")

    transport = ASGITransport(app=test_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/trigger-error", headers={"accept": "application/json"})
        assert response.status_code == 404
        data = response.json()
        assert data.get("detail") == "Custom resource missing"


@pytest.mark.asyncio
async def test_http_exception_handler():
    """Verify standard HTTPException handler returns clean JSON or HTML response."""
    test_app = FastAPI()
    register_exception_handlers(test_app)

    @test_app.get("/trigger-http-error")
    async def trigger_http():
        raise HTTPException(status_code=403, detail="Forbidden action")

    transport = ASGITransport(app=test_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/trigger-http-error", headers={"accept": "application/json"})
        assert response.status_code == 403
        data = response.json()
        assert data.get("detail") == "Forbidden action"


@pytest.mark.asyncio
async def test_generic_exception_handler():
    """Verify unhandled runtime exceptions are caught with a 500 error."""
    test_app = FastAPI()
    register_exception_handlers(test_app)

    @test_app.get("/trigger-unhandled")
    async def trigger_unhandled():
        raise RuntimeError("Unexpected server crash")

    transport = ASGITransport(app=test_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/trigger-unhandled", headers={"accept": "application/json"})
        assert response.status_code == 500

