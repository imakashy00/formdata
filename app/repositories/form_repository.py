# repositories/form_repository.py
from models.user import Form as FormDB
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select


class FormRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_by_name_and_project(self, name: str, project_id: str) -> FormDB | None:
        query = select(FormDB).where(FormDB.project_id == project_id, FormDB.name == name)
        result = await self.db.execute(query)
        return result.scalar_one_or_none()

    async def create(self, name: str, project_id: str, email: str) -> FormDB:
        new_form = FormDB(name=name, project_id=project_id, notification_email=email)
        self.db.add(new_form)
        await self.db.commit()
        await self.db.refresh(new_form)
        return new_form
