import pytest
from httpx import AsyncClient

from app.models.user import Form as FormDB
from app.models.user import Project, User


@pytest.mark.asyncio
async def test_get_form_settings_page(
    client: AsyncClient,
    auth_cookies: dict,
    sample_user: User,
    sample_project: Project,
    sample_form: FormDB,
):
    """Verify GET /projects/{project_id}/forms/{form_id}/settings loads form settings page."""
    response = await client.get(
        f"/projects/{sample_project.id}/forms/{sample_form.id}/settings/",
        cookies=auth_cookies,
    )
    assert response.status_code == 200
    assert sample_form.name in response.text
