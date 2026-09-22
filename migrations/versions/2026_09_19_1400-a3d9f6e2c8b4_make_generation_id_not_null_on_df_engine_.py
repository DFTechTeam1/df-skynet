"""make generation_id not null on df_engine_queues

- every row is written by the GenerationTask hooks (started/retried/succeeded/
  failed), which always carry a real generation_id; nothing writes to this
  table without one anymore now that 'enqueued' producer-side logging is gone

Revision ID: a3d9f6e2c8b4
Revises: f1c8d4a9e6b2
Create Date: 2026-09-19 14:00:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql

# revision identifiers, used by Alembic.
revision: str = "a3d9f6e2c8b4"
down_revision: Union[str, Sequence[str], None] = "f1c8d4a9e6b2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TABLE_NAME = "df_engine_queues"


def upgrade() -> None:
    """Upgrade schema."""
    op.alter_column(
        TABLE_NAME,
        "generation_id",
        existing_type=mysql.BIGINT(unsigned=True),
        nullable=False,
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.alter_column(
        TABLE_NAME,
        "generation_id",
        existing_type=mysql.BIGINT(unsigned=True),
        nullable=True,
    )
