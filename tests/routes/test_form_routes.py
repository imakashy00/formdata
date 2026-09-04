import pytest
from httpx import AsyncClient

from app.models.user import Form as FormDB
from app.models.user import Project, User


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
    assert response.status_code in (200, 201)
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


@pytest.mark.asyncio
async def test_get_form_submission_by_id_direct(
    client: AsyncClient,
    auth_cookies: dict,
    sample_user: User,
    sample_project: Project,
    sample_form: FormDB,
    sample_submission,
):
    """Verify direct browser GET for submission details returns full layout."""
    response = await client.get(
        f"/projects/{sample_project.id}/forms/{sample_form.id}/submissions/{sample_submission.id}",
        cookies=auth_cookies,
    )
    assert response.status_code == 200
    assert "Submission Details" in response.text
    assert "Back to List" in response.text
    assert str(sample_submission.id) in response.text


@pytest.mark.asyncio
async def test_get_form_submission_by_id_htmx(
    client: AsyncClient,
    auth_cookies: dict,
    sample_user: User,
    sample_project: Project,
    sample_form: FormDB,
    sample_submission,
):
    """Verify HTMX request for submission details returns card partial."""
    response = await client.get(
        f"/projects/{sample_project.id}/forms/{sample_form.id}/submissions/{sample_submission.id}",
        headers={"hx-request": "true"},
        cookies=auth_cookies,
    )
    assert response.status_code == 200
    assert "Submission Details" in response.text
    assert str(sample_submission.id) in response.text
    # Should contain the back link with HTMX navigation target
    assert 'hx-target="#tab-content"' in response.text
    assert 'hx-push-url="true"' in response.text


@pytest.mark.asyncio
async def test_get_form_submission_by_id_history_restore(
    client: AsyncClient,
    auth_cookies: dict,
    sample_user: User,
    sample_project: Project,
    sample_form: FormDB,
    sample_submission,
):
    """Verify HTMX history restore request returns full page template."""
    response = await client.get(
        f"/projects/{sample_project.id}/forms/{sample_form.id}/submissions/{sample_submission.id}",
        headers={"hx-request": "true", "HX-History-Restore-Request": "true"},
        cookies=auth_cookies,
    )
    assert response.status_code == 200
    assert "Submission Details" in response.text
    assert "<!DOCTYPE html>" in response.text or "<nav" in response.text
