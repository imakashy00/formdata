from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.user import Project


class ProjectRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def list_for_user(self, user_id: str) -> list[Project]:
        result = await self.db.execute(
            select(Project)
            .where(Project.user_id == user_id)
            .options(selectinload(Project.forms))
            .order_by(desc(Project.updated_at), desc(Project.created_at))
        )
        return list(result.scalars().unique().all())

    async def create(self, name: str, user_id: str) -> Project:
        new_project = Project(name=name, user_id=user_id)
        self.db.add(new_project)
        await self.db.commit()
        await self.db.refresh(new_project)
        return new_project

    async def get_for_user(self, project_id: str, user_id: str) -> Project | None:
        result = await self.db.execute(
            select(Project)
            .options(selectinload(Project.forms))
            .where(Project.user_id == user_id)
            .where(Project.id == project_id)
        )
        return result.scalar_one_or_none()

    async def delete_for_user(self, project_id: str, user_id: str) -> bool:
        project = await self.get_for_user(project_id, user_id)
        if not project:
            return False

        await self.db.delete(project)
        await self.db.commit()
        return True
