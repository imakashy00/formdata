"""merge multiple heads

Revision ID: 5481cd4cb6ce
Revises: 1f2e3d4c5b6a, 29946c07c323
Create Date: 2026-09-02 04:06:11.716129

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '5481cd4cb6ce'
down_revision: Union[str, Sequence[str], None] = ('1f2e3d4c5b6a', '29946c07c323')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
