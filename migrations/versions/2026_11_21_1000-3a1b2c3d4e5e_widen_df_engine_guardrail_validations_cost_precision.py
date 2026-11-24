"""widen df_engine_guardrail_validations.cost precision

- OpenRouter reports per-request cost in fractional USD (e.g. 0.002442),
  which DECIMAL(10,2) rounds to 0.00. Widen to DECIMAL(12,6), same as df_engine_generations.

Revision ID: 3a1b2c3d4e5e
Revises: 3a1b2c3d4e5d
Create Date: 2026-11-21 10:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "3a1b2c3d4e5e"
down_revision: Union[str, Sequence[str], None] = "3a1b2c3d4e5d"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TABLE_NAME = "df_engine_guardrail_validations"


def upgrade() -> None:
    """Upgrade schema."""
    op.alter_column(
        TABLE_NAME,
        "cost",
        type_=sa.DECIMAL(12, 6),
        existing_type=sa.DECIMAL(10, 2),
        existing_nullable=False,
        existing_server_default="0",
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.alter_column(
        TABLE_NAME,
        "cost",
        type_=sa.DECIMAL(10, 2),
        existing_type=sa.DECIMAL(12, 6),
        existing_nullable=False,
        existing_server_default="0",
    )
