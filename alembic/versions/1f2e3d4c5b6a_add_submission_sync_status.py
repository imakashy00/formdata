"""add submission sync status

Revision ID: 1f2e3d4c5b6a
Revises: e903a5e9b7b3
Create Date: 2026-09-02 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "1f2e3d4c5b6a"
down_revision: str | Sequence[str] | None = "e903a5e9b7b3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "submissions",
        sa.Column(
            "integration_sync_status",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
    )


def downgrade() -> None:
    op.drop_column("submissions", "integration_sync_status")
