from app.repositories.form_repository import FormRepository
from app.models.form import FormDB
from app.core.exceptions import DuplicateFormException

class FormService:
    def __init__(self, repo: FormRepository):
        self.repo = repo

    async def create_form(self, name: str, project_id: str, user_email: str) -> FormDB:
        # Business Rule Check
        existing_form = await self.repo.get_by_name_and_project(name, project_id)
        if existing_form:
            raise DuplicateFormException(name)
        
        # Entities Mapping & Save
        new_form = FormDB(
            name=name,
            project_id=project_id,
            notification_email=user_email,
        )
        return await self.repo.save(new_form)
