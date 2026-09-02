import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import Form as FormDB, Project, User


@pytest.mark.asyncio
async def test_create_form_in_project(
    client: AsyncClient,
    auth_cookies: dict,
    sample_user: User,
    sample_project: Project,
):
    """Verify POST /projects/{project_id}/forms creates a new form under a project."""
    response = await client.post(
        f"/projects/{sample_project.id}/forms",
        cookies=auth_cookies,
        data={"name": "Newsletter Subscription"},
    )
    assert response.status_code == 200
    assert "Newsletter Subscription" in response.text


@pytest.mark.asyncio
async def test_get_form_submissions_view(
    client: AsyncClient,
    auth_cookies: dict,
    sample_user: User,
    sample_project: Project,
    sample_form: FormDB,
):
    """Verify GET /projects/{project_id}/forms/{form_id}/submissions loads submission view."""
    response = await client.get(
        f"/projects/{sample_project.id}/forms/{sample_form.id}/submissions",
        cookies=auth_cookies,
    )
    assert response.status_code == 200
    assert sample_form.name in response.text


@pytest.mark.asyncio
async def test_get_form_setup_view(
    client: AsyncClient,
    auth_cookies: dict,
    sample_user: User,
    sample_project: Project,
    sample_form: FormDB,
):
    """Verify GET /projects/{project_id}/forms/{form_id}/setup loads integration code snippet."""
    response = await client.get(
        f"/projects/{sample_project.id}/forms/{sample_form.id}/setup",
        cookies=auth_cookies,
    )
    assert response.status_code == 200
    assert sample_form.public_id in response.text
