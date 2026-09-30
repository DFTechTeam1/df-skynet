"""widen df_engine_generations.cost precision

- OpenRouter reports per-request cost in fractional USD (e.g. 0.000656),
  which DECIMAL(10,2) truncates to 0.00. Widen to DECIMAL(12,6).

Revision ID: d5a2e9c1f7b3
Revises: c4f6a1b8d3e7
Create Date: 2026-09-29 19:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "d5a2e9c1f7b3"
down_revision: Union[str, Sequence[str], None] = "c4f6a1b8d3e7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TABLE_NAME = "df_engine_generations"


def upgrade() -> None:
    """Upgrade schema."""
    op.alter_column(TABLE_NAME, "cost", type_=sa.DECIMAL(12, 6), existing_type=sa.DECIMAL(10, 2))


def downgrade() -> None:
    """Downgrade schema."""
    op.alter_column(TABLE_NAME, "cost", type_=sa.DECIMAL(10, 2), existing_type=sa.DECIMAL(12, 6))
