import uuid
import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import Project, User
from app.repositories.project_repository import ProjectRepository


@pytest.mark.asyncio
async def test_project_repository_create_and_get(db_session: AsyncSession, sample_user: User):
    """Verify ProjectRepository create and get_for_user methods."""
    repo = ProjectRepository(db=db_session)
    project = await repo.create(name="Analytics Dashboard", user_id=sample_user.id)
    assert project.id is not None
    assert project.name == "Analytics Dashboard"

    fetched = await repo.get_for_user(project_id=project.id, user_id=sample_user.id)
    assert fetched is not None
    assert fetched.name == "Analytics Dashboard"


@pytest.mark.asyncio
async def test_project_repository_list_for_user(db_session: AsyncSession, sample_user: User):
    """Verify ProjectRepository list_for_user returns all user projects."""
    repo = ProjectRepository(db=db_session)
    await repo.create(name="Project Alpha", user_id=sample_user.id)
    await repo.create(name="Project Beta", user_id=sample_user.id)

    projects = await repo.list_for_user(user_id=sample_user.id)
    assert len(projects) >= 2
    names = [p.name for p in projects]
    assert "Project Alpha" in names
    assert "Project Beta" in names


@pytest.mark.asyncio
async def test_project_repository_exists_check(db_session: AsyncSession, sample_user: User):
    """Verify ProjectRepository get_for_user_project_name checks existing names."""
    repo = ProjectRepository(db=db_session)
    await repo.create(name="Unique Name", user_id=sample_user.id)

    exists = await repo.get_for_user_project_name(project_name="Unique Name", user_id=sample_user.id)
    assert exists is True

    not_exists = await repo.get_for_user_project_name(project_name="Non Existent", user_id=sample_user.id)
    assert not_exists is False


@pytest.mark.asyncio
async def test_project_repository_delete(db_session: AsyncSession, sample_user: User):
    """Verify ProjectRepository delete_for_user removes project from database."""
    repo = ProjectRepository(db=db_session)
    project = await repo.create(name="To Delete", user_id=sample_user.id)
    
    deleted = await repo.delete_for_user(project_id=project.id, user_id=sample_user.id)
    assert deleted is True

    fetched = await repo.get_for_user(project_id=project.id, user_id=sample_user.id)
    assert fetched is None
