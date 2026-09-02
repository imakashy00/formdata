import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import Form as FormDB


@pytest.mark.asyncio
async def test_submit_client_form_json(
    client: AsyncClient,
    sample_form: FormDB,
):
    """Verify POST /f/{public_id} processes form submissions sent via JSON."""
    response = await client.post(
        f"/f/{sample_form.public_id}",
        json={"name": "Hannah Abbott", "email": "hannah@example.com", "message": "Hi there!"},
        headers={"Accept": "application/json"},
    )
    assert response.status_code in (200, 302, 303)


@pytest.mark.asyncio
async def test_submit_client_form_invalid_public_id(client: AsyncClient):
    """Verify POST /f/{public_id} returns 404 for invalid public ID."""
    response = await client.post(
        "/f/nonexistent_form_public_id",
        json={"name": "Test"},
        headers={"Accept": "application/json"},
    )
    assert response.status_code == 404
