import uuid
import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import Form as FormDB, Project, Submission, SubmissionStatus
from app.repositories.form_repository import FormRepository


@pytest.mark.asyncio
async def test_form_repository_list_for_project(db_session: AsyncSession, sample_project: Project):
    """Verify FormRepository list_for_project returns all forms under a project."""
    repo = FormRepository(db=db_session)
    form1 = FormDB(
        id=uuid.uuid4(),
        project_id=sample_project.id,
        public_id="frm_test1",
        name="Signup Form",
    )
    db_session.add(form1)
    await db_session.commit()

    forms = await repo.list_for_project(project_id=sample_project.id)
    assert len(forms) >= 1
    assert any(f.name == "Signup Form" for f in forms)


@pytest.mark.asyncio
async def test_form_repository_get_by_id_and_project(db_session: AsyncSession, sample_project: Project, sample_form: FormDB):
    """Verify FormRepository get_by_id_and_project retrieval."""
    repo = FormRepository(db=db_session)
    found = await repo.get_by_id_and_project(form_id=sample_form.id, project_id=sample_project.id)
    assert found is not None
    assert found.id == sample_form.id


@pytest.mark.asyncio
async def test_form_repository_get_by_name_and_project(db_session: AsyncSession, sample_project: Project, sample_form: FormDB):
    """Verify FormRepository get_by_name_and_project uniqueness check."""
    repo = FormRepository(db=db_session)
    found = await repo.get_by_name_and_project(name=sample_form.name, project_id=sample_project.id)
    assert found is not None
    assert found.public_id == sample_form.public_id

    not_found = await repo.get_by_name_and_project(name="Unknown Name", project_id=sample_project.id)
    assert not_found is None
