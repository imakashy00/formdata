"""turnstile default and submission timestamp

Revision ID: a7c2d9f14b21
Revises: e1509a12d57e
Create Date: 2026-07-21 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a7c2d9f14b21'
down_revision: Union[str, Sequence[str], None] = 'e1509a12d57e'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.alter_column(
        'forms',
        'captcha_type',
        existing_type=sa.Enum('altcha', 'cloudflare_turnstile', name='captchatype'),
        server_default='cloudflare_turnstile',
    )
    op.add_column(
        'submissions',
        sa.Column(
            'created_at',
            sa.DateTime(timezone=True),
            server_default=sa.text('now()'),
            nullable=False,
        ),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.alter_column(
        'forms',
        'captcha_type',
        existing_type=sa.Enum('altcha', 'cloudflare_turnstile', name='captchatype'),
        server_default='altcha',
    )
    op.drop_column('submissions', 'created_at')
