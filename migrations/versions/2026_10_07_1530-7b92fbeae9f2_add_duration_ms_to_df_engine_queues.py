"""add_duration_ms_to_df_engine_queues

Revision ID: 7b92fbeae9f2
Revises: 8b860b9b6dde
Create Date: 2026-10-07 15:30:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "7b92fbeae9f2"
down_revision: Union[str, Sequence[str], None] = "8b860b9b6dde"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TABLE_NAME = "df_engine_queues"


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(TABLE_NAME, sa.Column("duration_ms", sa.Integer(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column(TABLE_NAME, "duration_ms")
