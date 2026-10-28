"""add_indexed_at_to_df_engine_upload_files

Revision ID: c5a7e9b1d3f4
Revises: a3e5c7b9d1f2
Create Date: 2026-10-17 10:00:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "c5a7e9b1d3f4"
down_revision: Union[str, Sequence[str], None] = "a3e5c7b9d1f2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("df_engine_upload_files", sa.Column("indexed_at", sa.DateTime(), nullable=True))


def downgrade() -> None:
    op.drop_column("df_engine_upload_files", "indexed_at")
