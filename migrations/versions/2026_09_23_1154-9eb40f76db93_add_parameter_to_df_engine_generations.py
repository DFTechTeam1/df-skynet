"""add parameter column to df_engine_generations

- stores the raw `schema.parameter` dict from the generation request, so it
  can be shown back to the user alongside the generation record.

Revision ID: 9eb40f76db93
Revises: b8e1c3f6a2d9
Create Date: 2026-09-23 11:54:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "9eb40f76db93"
down_revision: Union[str, Sequence[str], None] = "b8e1c3f6a2d9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TABLE_NAME = "df_engine_generations"


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(TABLE_NAME, sa.Column("parameter", sa.JSON(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column(TABLE_NAME, "parameter")
