"""replace is_favourite with favourited_at

Revision ID: c4f6a1b8d3e7
Revises: 9eb40f76db93
Create Date: 2026-09-24 10:00:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "c4f6a1b8d3e7"
down_revision: Union[str, Sequence[str], None] = "9eb40f76db93"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TABLE_NAME = "df_engine_generation_results"


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(TABLE_NAME, sa.Column("favourited_at", sa.DateTime, nullable=True))
    op.execute(f"UPDATE {TABLE_NAME} SET favourited_at = updated_at WHERE is_favourite = true")
    op.drop_column(TABLE_NAME, "is_favourite")


def downgrade() -> None:
    """Downgrade schema."""
    op.add_column(TABLE_NAME, sa.Column("is_favourite", sa.Boolean, nullable=False, server_default=sa.false()))
    op.execute(f"UPDATE {TABLE_NAME} SET is_favourite = true WHERE favourited_at IS NOT NULL")
    op.drop_column(TABLE_NAME, "favourited_at")
