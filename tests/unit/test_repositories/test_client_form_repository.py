import uuid
import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import Form as FormDB, Project
from app.repositories.client_form_repository import ClientFormRepository


@pytest.mark.asyncio
async def test_client_form_repository_get_with_public_id(db_session: AsyncSession, sample_form: FormDB):
    """Verify ClientFormRepository retrieves form by its public client ID."""
    repo = ClientFormRepository(db=db_session)
    form = await repo.get_form_with_public_id(form_id=sample_form.public_id)
    assert form is not None
    assert form.id == sample_form.id

    missing = await repo.get_form_with_public_id(form_id="nonexistent_id")
    assert missing is None


@pytest.mark.asyncio
async def test_client_form_repository_get_enabled_integrations_empty(db_session: AsyncSession, sample_form: FormDB):
    """Verify ClientFormRepository returns empty list when no integrations are linked."""
    repo = ClientFormRepository(db=db_session)
    integrations = await repo.get_enabled_integrations(form_id=sample_form.id)
    assert isinstance(integrations, list)
    assert len(integrations) == 0
