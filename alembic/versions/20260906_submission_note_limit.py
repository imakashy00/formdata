"""increase submission note length to 500 characters"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260906_submission_note_limit"
down_revision: str | Sequence[str] | None = "20260905_autoresponder_key"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.alter_column(
        "submissions",
        "note",
        existing_type=sa.String(length=200),
        type_=sa.String(length=500),
        existing_nullable=True,
    )


def downgrade() -> None:
    op.alter_column(
        "submissions",
        "note",
        existing_type=sa.String(length=500),
        type_=sa.String(length=200),
        existing_nullable=True,
    )
