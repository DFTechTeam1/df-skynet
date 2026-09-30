"""drop df_engine_enhancer_details

- Superseded by prompt/full_prompt already present on df_engine_generations.

Revision ID: c6a1e4b9d2f8
Revises: b4f8d3fac7e5
Create Date: 2026-09-30 10:10:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.mysql import BIGINT

revision: str = "c6a1e4b9d2f8"
down_revision: Union[str, Sequence[str], None] = "b4f8d3fac7e5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TABLE_NAME = "df_engine_enhancer_details"


def upgrade() -> None:
    """Upgrade schema."""
    op.drop_table(TABLE_NAME)


def downgrade() -> None:
    """Downgrade schema."""
    op.create_table(
        TABLE_NAME,
        sa.Column("id", BIGINT(unsigned=True), primary_key=True, autoincrement=True),
        sa.Column("generation_id", BIGINT(unsigned=True), sa.ForeignKey("df_engine_generations.id"), nullable=False),
        sa.Column("raw", sa.Text, nullable=True),
        sa.Column("enhanced", sa.Text, nullable=True),
    )
