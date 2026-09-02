import pytest
from httpx import AsyncClient

from app.models.user import Form as FormDB
from app.models.user import Project, User


@pytest.mark.asyncio
async def test_get_dashboard_authenticated(
    client: AsyncClient,
    auth_cookies: dict,
    sample_user: User,
    sample_project: Project,
    sample_form: FormDB,
):
    """Verify GET / renders the main dashboard overview with metric counters and projects."""
    response = await client.get("/", cookies=auth_cookies)
    assert response.status_code == 200
    assert (
        "dashboard" in response.text.lower()
        or "projects" in response.text.lower()
        or "submissions" in response.text.lower()
    )


@pytest.mark.asyncio
async def test_get_dashboard_unauthenticated_renders_landing(client: AsyncClient):
    """Verify GET / renders public landing page when unauthenticated."""
    response = await client.get("/")
    assert response.status_code == 200
    assert (
        "Formdata" in response.text
        or "Sign in" in response.text
        or "Login" in response.text
    )
