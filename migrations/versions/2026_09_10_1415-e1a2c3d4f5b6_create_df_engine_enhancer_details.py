"""create df_engine_enhancer_details

Revision ID: e1a2c3d4f5b6
Revises: d0f1b2c3e4a5
Create Date: 2026-09-10 14:15:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.mysql import BIGINT


# revision identifiers, used by Alembic.
revision: str = "e1a2c3d4f5b6"
down_revision: Union[str, Sequence[str], None] = "d0f1b2c3e4a5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TABLE_NAME = "df_engine_enhancer_details"


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        TABLE_NAME,
        sa.Column("id", BIGINT(unsigned=True), primary_key=True, autoincrement=True),
        sa.Column("generation_id", BIGINT(unsigned=True), sa.ForeignKey("df_engine_generations.id"), nullable=False),
        sa.Column("raw", sa.Text, nullable=True),
        sa.Column("enhanced", sa.Text, nullable=True),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table(TABLE_NAME)
