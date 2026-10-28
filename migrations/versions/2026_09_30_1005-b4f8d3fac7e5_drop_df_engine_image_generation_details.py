"""drop df_engine_image_generation_details

- Superseded by enhance_id/x_min/x_max/y_min/y_max on df_engine_generations.

Revision ID: b4f8d3fac7e5
Revises: a3f7c2e9b6d4
Create Date: 2026-09-30 10:05:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.mysql import BIGINT

revision: str = "b4f8d3fac7e5"
down_revision: Union[str, Sequence[str], None] = "a3f7c2e9b6d4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TABLE_NAME = "df_engine_image_generation_details"


def upgrade() -> None:
    """Upgrade schema."""
    op.drop_table(TABLE_NAME)


def downgrade() -> None:
    """Downgrade schema."""
    op.create_table(
        TABLE_NAME,
        sa.Column("id", BIGINT(unsigned=True), primary_key=True, autoincrement=True),
        sa.Column("generation_id", BIGINT(unsigned=True), sa.ForeignKey("df_engine_generations.id"), nullable=False),
        sa.Column("enhancer_id", BIGINT(unsigned=True), sa.ForeignKey("df_engine_generations.id"), nullable=True),
        sa.Column("parameter", sa.JSON, nullable=True),
        sa.Column("x_min", sa.DECIMAL(10, 2), nullable=True),
        sa.Column("x_max", sa.DECIMAL(10, 2), nullable=True),
        sa.Column("y_min", sa.DECIMAL(10, 2), nullable=True),
        sa.Column("y_max", sa.DECIMAL(10, 2), nullable=True),
    )
