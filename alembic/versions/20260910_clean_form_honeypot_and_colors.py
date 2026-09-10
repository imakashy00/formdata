"""remove hex color hash prefix and honeypot underscore

Revision ID: 20260910_clean_honeypot_and_colors
Revises: 20260906_submission_note_limit
Create Date: 2026-09-10
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260910_clean_honeypot_and_colors"
down_revision: str | Sequence[str] | None = "20260906_submission_note_limit"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # 1. Strip '#' prefix from existing hex color values in database
    op.execute(
        "UPDATE forms SET "
        "sub_bg_color = LTRIM(sub_bg_color, '#'), "
        "sub_txt_color = LTRIM(sub_txt_color, '#'), "
        "sub_lnk_color = LTRIM(sub_lnk_color, '#')"
    )

    # 2. Strip leading '_' from existing honeypot field values in database
    op.execute("UPDATE forms SET honeypot = LTRIM(honeypot, '_')")

    # 3. Alter columns: update server defaults and lengths
    op.alter_column(
        "forms",
        "sub_bg_color",
        existing_type=sa.String(length=7),
        type_=sa.String(length=6),
        server_default="ffffff",
        existing_nullable=False,
    )
    op.alter_column(
        "forms",
        "sub_txt_color",
        existing_type=sa.String(length=7),
        type_=sa.String(length=6),
        server_default="000000",
        existing_nullable=False,
    )
    op.alter_column(
        "forms",
        "sub_lnk_color",
        existing_type=sa.String(length=7),
        type_=sa.String(length=6),
        server_default="3b82f6",
        existing_nullable=False,
    )
    op.alter_column(
        "forms",
        "honeypot",
        existing_type=sa.String(length=36),
        type_=sa.String(length=36),
        server_default="gotcha",
        existing_nullable=False,
    )


def downgrade() -> None:
    # 1. Restore column types and server defaults
    op.alter_column(
        "forms",
        "sub_bg_color",
        existing_type=sa.String(length=6),
        type_=sa.String(length=7),
        server_default="#ffffff",
        existing_nullable=False,
    )
    op.alter_column(
        "forms",
        "sub_txt_color",
        existing_type=sa.String(length=6),
        type_=sa.String(length=7),
        server_default="#000000",
        existing_nullable=False,
    )
    op.alter_column(
        "forms",
        "sub_lnk_color",
        existing_type=sa.String(length=6),
        type_=sa.String(length=7),
        server_default="#3b82f6",
        existing_nullable=False,
    )
    op.alter_column(
        "forms",
        "honeypot",
        existing_type=sa.String(length=36),
        type_=sa.String(length=36),
        server_default="_gotcha",
        existing_nullable=False,
    )

    # 2. Prepend '#' back to hex colors if missing
    op.execute(
        "UPDATE forms SET "
        "sub_bg_color = '#' || sub_bg_color WHERE sub_bg_color NOT LIKE '#%'"
    )
    op.execute(
        "UPDATE forms SET "
        "sub_txt_color = '#' || sub_txt_color WHERE sub_txt_color NOT LIKE '#%'"
    )
    op.execute(
        "UPDATE forms SET "
        "sub_lnk_color = '#' || sub_lnk_color WHERE sub_lnk_color NOT LIKE '#%'"
    )

    # 3. Prepend '_' back to honeypot if missing
    op.execute(
        "UPDATE forms SET honeypot = '_' || honeypot WHERE honeypot NOT LIKE '_%'"
    )
