"""add autoresponder recipient field key"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260905_autoresponder_key"
down_revision: str | Sequence[str] | None = "74ff3ae2c739"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "forms", sa.Column("autoresponse_recipient_key", sa.String(100), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("forms", "autoresponse_recipient_key")
