"""merge heads

Revision ID: 901885be491c
Revises: 31f06c7aeef3, a7c2d9f14b21
Create Date: 2026-07-21 23:09:01.744919

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '901885be491c'
down_revision: Union[str, Sequence[str], None] = ('31f06c7aeef3', 'a7c2d9f14b21')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
