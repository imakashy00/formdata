from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import Form as FormDB


class ClientFormRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_form_with_public_id(self, form_id: str):
        query = select(FormDB).where(FormDB.public_id == form_id)
        result = await self.db.execute(query)
        return result.scalar_one_or_none()
