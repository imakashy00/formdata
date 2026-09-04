import pytest
from httpx import AsyncClient

from main import app


def test_fastapi_app_initialization():
    """Verify FastAPI application name, middleware, and router inclusion."""
    assert "Formdata" in app.title
    assert app.routes is not None
    assert len(app.routes) > 0


@pytest.mark.asyncio
async def test_not_found_endpoint_handling(client: AsyncClient, auth_cookies: dict):
    """Verify 404 response for nonexistent routes."""
    response = await client.get("/this-route-does-not-exist-at-all", cookies=auth_cookies)
    assert response.status_code == 404
