# repositories/form_repository.py
from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.user import Form as FormDB
from app.models.user import (
    FormIntegration,
    Integration,
    IntegrationProvider,
    Project,
    Submission,
    SubmissionStatus,
)


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
        self, form_id: str | UUID, project_id: str | UUID, include_submissions: bool = False
    ) -> FormDB | None:
        f_uuid = UUID(str(form_id)) if not isinstance(form_id, UUID) else form_id
        p_uuid = UUID(str(project_id)) if not isinstance(project_id, UUID) else project_id
        query = select(FormDB).where(
            FormDB.id == f_uuid, FormDB.project_id == p_uuid
        )
        if include_submissions:
            query = query.options(selectinload(FormDB.submissions))
        result = await self.db.execute(query)
        return result.scalar_one_or_none()

    async def get_by_name_and_project(
        self, name: str, project_id: str | UUID
    ) -> FormDB | None:
        p_uuid = UUID(str(project_id)) if not isinstance(project_id, UUID) else project_id
        query = select(FormDB).where(
            FormDB.project_id == p_uuid, FormDB.name == name
        )
        result = await self.db.execute(query)
        return result.scalar_one_or_none()

    async def get_integration_map(
        self, form_id: str | UUID, project_id: str | UUID
    ) -> dict[str, dict]:
        form = await self.get_by_id_and_project(form_id, project_id)
        if not form:
            return {}

        query = (
            select(
                FormIntegration.config,
                Integration.provider,
                Integration.access_token,
            )
            .join(Integration, Integration.id == FormIntegration.integration_id)
            .where(FormIntegration.form_id == form.id)
        )
        result = await self.db.execute(query)
        integration_map: dict[str, dict] = {}
        for config, provider, access_token in result.all():
            cfg = dict(config or {})
            if access_token:
                if provider == IntegrationProvider.GOOGLE_SHEETS and "access_token" not in cfg:
                    cfg["access_token"] = access_token
                elif provider == IntegrationProvider.NOTION and "notion_token" not in cfg:
                    cfg["notion_token"] = access_token
            integration_map[provider.value] = cfg

        if "google_sheets" not in integration_map or not integration_map["google_sheets"].get("access_token"):
            p_uuid = UUID(str(project_id)) if not isinstance(project_id, UUID) else project_id
            project = await self.db.get(Project, p_uuid)
            if project:
                user_integ_res = await self.db.execute(
                    select(Integration).where(
                        Integration.user_id == project.user_id,
                        Integration.provider == IntegrationProvider.GOOGLE_SHEETS,
                        Integration.enabled.is_(True),
                    )
                )
                user_integ = user_integ_res.scalar_one_or_none()
                if user_integ and user_integ.access_token:
                    current_gs = integration_map.get("google_sheets", {})
                    current_gs["access_token"] = user_integ.access_token
                    if "sheet_url" not in current_gs and user_integ.integration_metadata:
                        current_gs["sheet_url"] = user_integ.integration_metadata.get("sheet_url", "")
                    if "worksheet_name" not in current_gs and user_integ.integration_metadata:
                        current_gs["worksheet_name"] = user_integ.integration_metadata.get("worksheet_name", "Sheet1")
                    integration_map["google_sheets"] = current_gs

        return integration_map

    async def get_enabled_integrations(self, form_id: str | UUID) -> list[dict]:
        form_uuid = UUID(str(form_id)) if not isinstance(form_id, UUID) else form_id
        result = await self.db.execute(
            select(
                Integration.provider,
                Integration.access_token,
                Integration.refresh_token,
                Integration.integration_metadata,
                Integration.enabled,
                FormIntegration.enabled.label("form_enabled"),
                FormIntegration.config,
            )
            .join(Integration, Integration.id == FormIntegration.integration_id)
            .where(FormIntegration.form_id == form_uuid)
            .where(FormIntegration.enabled.is_(True))
            .where(Integration.enabled.is_(True))
        )

        integrations: list[dict] = []
        for row in result.all():
            (
                provider,
                access_token,
                refresh_token,
                metadata,
                enabled,
                form_enabled,
                config,
            ) = row
            integrations.append(
                {
                    "provider": provider.value,
                    "access_token": access_token,
                    "refresh_token": refresh_token,
                    "metadata": dict(metadata or {}),
                    "enabled": enabled and form_enabled,
                    "config": dict(config or {}),
                }
            )

        return integrations

    async def upsert_form_integration(
        self,
        form_id: str | UUID,
        project_id: str | UUID,
        provider: IntegrationProvider,
        config: dict,
        enabled: bool = True,
    ) -> FormIntegration:
        form = await self.get_by_id_and_project(form_id, project_id)
        if not form:
            raise ValueError("Form not found")

        p_uuid = UUID(str(project_id)) if not isinstance(project_id, UUID) else project_id
        project = await self.db.get(Project, p_uuid)
        if project is None:
            raise ValueError("Project not found")

        integration = await self.db.execute(
            select(Integration).where(
                Integration.user_id == project.user_id,
                Integration.provider == provider,
            )
        )
        integration = integration.scalar_one_or_none()
        if integration is None:
            integration = Integration(
                user_id=project.user_id,
                provider=provider,
                enabled=True,
            )
            self.db.add(integration)
            await self.db.flush()

        if provider == IntegrationProvider.NOTION and config.get("notion_token"):
            integration.access_token = config["notion_token"]
        elif provider == IntegrationProvider.GOOGLE_SHEETS:
            if config.get("access_token"):
                integration.access_token = config["access_token"]
            integration.integration_metadata = {
                "sheet_url": config.get("sheet_url"),
                "worksheet_name": config.get("worksheet_name") or "Sheet1",
                "spreadsheet_id": config.get("spreadsheet_id"),
            }
        else:
            integration.integration_metadata = dict(config or {})
        integration.enabled = enabled

        existing = await self.db.execute(
            select(FormIntegration).where(
                FormIntegration.form_id == form.id,
                FormIntegration.integration_id == integration.id,
            )
        )
        form_integration = existing.scalar_one_or_none()
        if form_integration is None:
            form_integration = FormIntegration(
                form_id=form.id,
                integration_id=integration.id,
                enabled=enabled,
                config={},
            )
            self.db.add(form_integration)

        form_integration.config = dict(config or {})
        form_integration.enabled = enabled
        await self.db.commit()
        await self.db.refresh(integration)
        await self.db.refresh(form_integration)
        return form_integration

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
