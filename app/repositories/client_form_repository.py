from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import (
    Form as FormDB,
)
from app.models.user import (
    FormIntegration,
)
from app.models.user import (
    Integration as IntegrationDB,
)


class ClientFormRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_form_with_public_id(self, form_id: str):
        query = select(FormDB).where(FormDB.public_id == form_id)
        result = await self.db.execute(query)
        return result.scalar_one_or_none()

    async def get_enabled_integrations(self, form_id: str) -> list[dict]:
        query = (
            select(
                IntegrationDB.provider,
                IntegrationDB.access_token,
                IntegrationDB.refresh_token,
                IntegrationDB.integration_metadata,
                FormIntegration.config,
            )
            .join(IntegrationDB, IntegrationDB.id == FormIntegration.integration_id)
            .where(FormIntegration.form_id == form_id)
            .where(FormIntegration.enabled.is_(True))
            .where(IntegrationDB.enabled.is_(True))
        )
        result = await self.db.execute(query)

        integrations: list[dict] = []
        for provider, access_token, refresh_token, metadata, config in result.all():
            integrations.append(
                {
                    "provider": provider.value,
                    "access_token": access_token,
                    "refresh_token": refresh_token,
                    "metadata": dict(metadata or {}),
                    "config": dict(config or {}),
                }
            )

        return integrations
