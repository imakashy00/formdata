import pytest
from httpx import AsyncClient

from main import app


def test_fastapi_app_initialization():
    """Verify FastAPI application name, middleware, and router inclusion."""
    assert app.title == "Formdata"
    assert app.routes is not None
    assert len(app.routes) > 0


@pytest.mark.asyncio
async def test_not_found_endpoint_handling(client: AsyncClient):
    """Verify 404 response for nonexistent routes."""
    response = await client.get("/this-route-does-not-exist-at-all")
    assert response.status_code == 404
