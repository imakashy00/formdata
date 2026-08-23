# repositories/form_repository.py
from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.user import Form as FormDB
from app.models.user import Submission, SubmissionStatus


class FormRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def list_for_project(self, project_id: UUID) -> list[FormDB]:
        result = await self.db.execute(
            select(FormDB)
            .where(FormDB.project_id == project_id)
            .options(selectinload(FormDB.submissions))
        )
        return list(result.scalars().all())

    async def get_by_id_and_project(
        self, form_id: str, project_id: str, include_submissions: bool = False
    ) -> FormDB | None:
        query = select(FormDB).where(
            FormDB.id == form_id, FormDB.project_id == project_id
        )
        if include_submissions:
            query = query.options(selectinload(FormDB.submissions))
        result = await self.db.execute(query)
        return result.scalar_one_or_none()

    async def get_by_name_and_project(
        self, name: str, project_id: str
    ) -> FormDB | None:
        query = select(FormDB).where(
            FormDB.project_id == project_id, FormDB.name == name
        )
        result = await self.db.execute(query)
        return result.scalar_one_or_none()

    async def create(self, name: str, project_id: str, email: str) -> FormDB:
        new_form = FormDB(name=name, project_id=project_id, notification_email=email)
        self.db.add(new_form)
        await self.db.commit()
        await self.db.refresh(new_form)
        return new_form

    async def update_template(
        self, form_id: str, project_id: str, subject: str, body: str
    ) -> FormDB | None:
        form = await self.get_by_id_and_project(form_id, project_id)
        if not form:
            return None

        form.customer_subject = subject
        form.customer_body = body
        await self.db.commit()
        return form

    async def delete_by_id_and_project(self, form_id: str, project_id: str) -> bool:
        stmt = (
            delete(FormDB)
            .where(FormDB.id == form_id, FormDB.project_id == project_id)
            .returning(FormDB.id)
        )
        result = await self.db.execute(stmt)
        deleted_id = result.scalar_one_or_none()
        if deleted_id is None:
            return False

        await self.db.commit()
        return True

    async def get_submission(self, form_id: str, submission_id: str):
        result = await self.db.execute(
            select(Submission).where(
                Submission.id == submission_id, Submission.form_id == form_id
            )
        )
        return result.scalar_one_or_none()

    async def set_submission_opened(self, submission: Submission) -> Submission:
        if not submission.opened:
            submission.opened = True
            await self.db.commit()
            await self.db.refresh(submission)
        return submission

    async def update_submission_status(
        self, submission: Submission, action: str
    ) -> Submission:
        if action == "spam":
            submission.status = SubmissionStatus.REJECTED
        elif action == "unspam":
            submission.status = SubmissionStatus.ACCEPTED
        else:
            raise ValueError("Invalid action parameter.")

        await self.db.commit()
        await self.db.refresh(submission)
        return submission

    async def delete_submission(self, submission: Submission) -> None:
        await self.db.delete(submission)
        await self.db.commit()

    async def list_submissions(self, form_id: str, status: str | None = None):
        query = select(Submission).where(Submission.form_id == form_id)
        if status:
            query = query.where(Submission.status == status)
        result = await self.db.execute(query)
        return list(result.scalars().all())
