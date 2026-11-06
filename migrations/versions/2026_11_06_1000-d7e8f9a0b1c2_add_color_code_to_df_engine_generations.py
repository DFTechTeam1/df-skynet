"""add color_code to df_engine_generations

Revision ID: d7e8f9a0b1c2
Revises: b4c5d6e7f8a9
Create Date: 2026-11-06 10:00:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "d7e8f9a0b1c2"
down_revision: Union[str, Sequence[str], None] = "b4c5d6e7f8a9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column("df_engine_generations", sa.Column("color_code", sa.String(7), nullable=True, server_default=None))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("df_engine_generations", "color_code")
