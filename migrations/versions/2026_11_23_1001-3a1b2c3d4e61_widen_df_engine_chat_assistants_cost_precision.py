"""widen df_engine_chat_assistants.cost precision

- OpenRouter reports per-request cost in fractional USD (e.g. 0.002442),
  which DECIMAL(10,2) rounds to 0.00, so chat spend never reached the project cost check.
  Widen to DECIMAL(12,6), same as df_engine_generations and df_engine_guardrail_validations.
- Existing rows keep what was stored (0.00 stays 0.00); only new rows get the precision.
- Downgrade narrows back to 2 decimals and rounds fractional costs.

Revision ID: 3a1b2c3d4e61
Revises: 3a1b2c3d4e60
Create Date: 2026-11-23 10:01:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "3a1b2c3d4e61"
down_revision: Union[str, Sequence[str], None] = "3a1b2c3d4e60"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TABLE_NAME = "df_engine_chat_assistants"


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
