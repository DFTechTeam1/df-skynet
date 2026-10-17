"""add_indexed_at_to_df_engine_generation_results

Revision ID: d6b8f0c2e4a5
Revises: c5a7e9b1d3f4
Create Date: 2026-10-17 10:01:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "d6b8f0c2e4a5"
down_revision: Union[str, Sequence[str], None] = "c5a7e9b1d3f4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("df_engine_generation_results", sa.Column("indexed_at", sa.DateTime(), nullable=True))


def downgrade() -> None:
    op.drop_column("df_engine_generation_results", "indexed_at")
