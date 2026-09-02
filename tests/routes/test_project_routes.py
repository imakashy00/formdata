import pytest
from httpx import AsyncClient

from app.models.user import Project, User


@pytest.mark.asyncio
async def test_get_projects_list(
    client: AsyncClient,
    auth_cookies: dict,
    sample_user: User,
    sample_project: Project,
):
    """Verify GET /projects lists all projects for current user."""
    response = await client.get("/projects", cookies=auth_cookies)
    assert response.status_code == 200
    assert sample_project.name in response.text


@pytest.mark.asyncio
async def test_create_project_success(
    client: AsyncClient,
    auth_cookies: dict,
    sample_user: User,
):
    """Verify POST /projects creates a new project."""
    response = await client.post(
        "/projects",
        cookies=auth_cookies,
        data={"name": "New Awesome API"},
    )
    assert response.status_code == 200
    assert "New Awesome API" in response.text


@pytest.mark.asyncio
async def test_delete_project(
    client: AsyncClient,
    auth_cookies: dict,
    sample_user: User,
    sample_project: Project,
):
    """Verify DELETE /projects/{project_id} removes project."""
    response = await client.delete(
        f"/projects/{sample_project.id}",
        cookies=auth_cookies,
    )
    assert response.status_code == 200
