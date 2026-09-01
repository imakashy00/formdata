"""add form heading

Revision ID: 29946c07c323
Revises: bb0ab8cb9629
Create Date: 2026-09-01 23:21:47.127449

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "29946c07c323"
down_revision: str | Sequence[str] | None = "bb0ab8cb9629"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    # 1. Add your new form heading column
    op.add_column("forms", sa.Column("heading", sa.String(length=200), nullable=True))

    # 2. Drop the existing foreign key constraint so we can change the type
    op.drop_constraint(
        "subscriptions_user_id_fkey", "subscriptions", type_="foreignkey"
    )

    # 3. Alter column to UUID and cast existing text/string values to UUID explicitly
    op.alter_column(
        "subscriptions",
        "user_id",
        existing_type=sa.String(length=36),
        type_=sa.UUID(),
        existing_nullable=False,
        postgresql_using="user_id::uuid",  # This safely converts legacy string values to UUIDs
    )

    # 4. Re-create the foreign key constraint pointing to the UUID primary key
    op.create_foreign_key(
        "subscriptions_user_id_fkey",
        "subscriptions",
        "users",
        ["user_id"],
        ["id"],
        ondelete="CASCADE",
    )


def downgrade() -> None:
    """Downgrade schema."""
    # 1. Revert constraints and types back to original state if rolled back
    op.drop_constraint(
        "subscriptions_user_id_fkey", "subscriptions", type_="foreignkey"
    )

    op.alter_column(
        "subscriptions",
        "user_id",
        existing_type=sa.UUID(),
        type_=sa.String(length=36),
        existing_nullable=False,
    )

    op.create_foreign_key(
        "subscriptions_user_id_fkey",
        "subscriptions",
        "users",
        ["user_id"],
        ["id"],
        ondelete="CASCADE",
    )

    # 2. Drop the form heading column
    op.drop_column("forms", "heading")
