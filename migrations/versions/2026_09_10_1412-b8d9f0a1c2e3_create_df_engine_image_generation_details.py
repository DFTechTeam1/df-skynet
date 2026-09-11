"""create df_engine_image_generation_details

Revision ID: b8d9f0a1c2e3
Revises: a7c8e9f0b1d2
Create Date: 2026-09-10 14:12:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.mysql import BIGINT


# revision identifiers, used by Alembic.
revision: str = "b8d9f0a1c2e3"
down_revision: Union[str, Sequence[str], None] = "a7c8e9f0b1d2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TABLE_NAME = "df_engine_image_generation_details"


def upgrade() -> None:
    """Upgrade schema."""
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


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table(TABLE_NAME)
