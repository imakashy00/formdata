"""add redirect, turnstile and autoresponse column to form table.

Revision ID: bb0ab8cb9629
Revises: 09c1cf9d2cd9
Create Date: 2026-08-28 18:20:31.769289

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "bb0ab8cb9629"
down_revision: Union[str, None] = "09c1cf9d2cd9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # --- 1. HANDLE 'redirect' COLUMN ---
    op.add_column("forms", sa.Column("redirect", sa.Boolean(), nullable=True))
    op.execute("UPDATE forms SET redirect = FALSE WHERE redirect IS NULL")
    op.alter_column("forms", "redirect", nullable=False)

    # --- 2. HANDLE 'turnstile_enabled' COLUMN ---
    op.add_column("forms", sa.Column("turnstile_enabled", sa.Boolean(), nullable=True))
    op.execute(
        "UPDATE forms SET turnstile_enabled = FALSE WHERE turnstile_enabled IS NULL"
    )
    op.alter_column("forms", "turnstile_enabled", nullable=False)

    # --- 3. HANDLE 'autoresponse' COLUMN ---
    op.add_column("forms", sa.Column("autoresponse", sa.Boolean(), nullable=True))
    op.execute("UPDATE forms SET autoresponse = FALSE WHERE autoresponse IS NULL")
    op.alter_column("forms", "autoresponse", nullable=False)


def downgrade() -> None:
    op.drop_column("forms", "autoresponse")
    op.drop_column("forms", "turnstile_enabled")
    op.drop_column("forms", "redirect")
