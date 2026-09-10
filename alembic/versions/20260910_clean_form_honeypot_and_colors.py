"""remove hex color hash prefix and honeypot underscore

Revision ID: 20260910_clean_form_fields
Revises: 20260906_submission_note_limit
Create Date: 2026-09-10
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260910_clean_form_fields"
down_revision: str | Sequence[str] | None = "20260906_submission_note_limit"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # 1. Clean existing previous values in database to avoid truncation errors
    op.execute(
        """
        UPDATE forms SET
            sub_bg_color = CASE
                WHEN sub_bg_color IS NULL OR TRIM(sub_bg_color) = '' THEN 'ffffff'
                ELSE SUBSTRING(LTRIM(TRIM(sub_bg_color), '#') FROM 1 FOR 6)
            END,
            sub_txt_color = CASE
                WHEN sub_txt_color IS NULL OR TRIM(sub_txt_color) = '' THEN '000000'
                ELSE SUBSTRING(LTRIM(TRIM(sub_txt_color), '#') FROM 1 FOR 6)
            END,
            sub_lnk_color = CASE
                WHEN sub_lnk_color IS NULL OR TRIM(sub_lnk_color) = '' THEN '3b82f6'
                ELSE SUBSTRING(LTRIM(TRIM(sub_lnk_color), '#') FROM 1 FOR 6)
            END,
            honeypot = CASE
                WHEN honeypot IS NULL OR TRIM(LTRIM(TRIM(honeypot), '_')) = '' THEN 'gotcha'
                ELSE SUBSTRING(TRIM(LTRIM(TRIM(honeypot), '_')) FROM 1 FOR 36)
            END
        """
    )

    # 2. Alter columns: update server defaults and lengths
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
    # 1. Restore column types and server defaults first (to allow 7 chars)
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

    # 2. Prepend '#' back to hex colors and '_' to honeypot
    op.execute(
        """
        UPDATE forms SET
            sub_bg_color = CASE
                WHEN sub_bg_color IS NULL OR TRIM(sub_bg_color) = '' THEN '#ffffff'
                WHEN sub_bg_color LIKE '#%' THEN sub_bg_color
                ELSE '#' || sub_bg_color
            END,
            sub_txt_color = CASE
                WHEN sub_txt_color IS NULL OR TRIM(sub_txt_color) = '' THEN '#000000'
                WHEN sub_txt_color LIKE '#%' THEN sub_txt_color
                ELSE '#' || sub_txt_color
            END,
            sub_lnk_color = CASE
                WHEN sub_lnk_color IS NULL OR TRIM(sub_lnk_color) = '' THEN '#3b82f6'
                WHEN sub_lnk_color LIKE '#%' THEN sub_lnk_color
                ELSE '#' || sub_lnk_color
            END,
            honeypot = CASE
                WHEN honeypot IS NULL OR TRIM(honeypot) = '' THEN '_gotcha'
                WHEN honeypot LIKE '_%' THEN honeypot
                ELSE '_' || honeypot
            END
        """
    )

