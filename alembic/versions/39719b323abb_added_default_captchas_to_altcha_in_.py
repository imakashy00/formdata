"""added default captchas to altcha in form table

Revision ID: 39719b323abb
Revises: 38a0018b2fbd
Create Date: 2026-07-18 23:46:46.930249
"""

from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = "39719b323abb"
down_revision: Union[str, Sequence[str], None] = "38a0018b2fbd"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.execute("""
        ALTER TABLE forms
        ALTER COLUMN captcha_type
        SET DEFAULT 'altcha';
    """)


def downgrade() -> None:
    """Downgrade schema."""
    op.execute("""
        ALTER TABLE forms
        ALTER COLUMN captcha_type
        SET DEFAULT 'cloudflare_turnstile';
    """)
