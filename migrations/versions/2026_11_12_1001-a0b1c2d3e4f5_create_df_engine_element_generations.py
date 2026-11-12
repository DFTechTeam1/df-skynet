"""create df_engine_element_generations

Revision ID: a0b1c2d3e4f5
Revises: f9a0b1c2d3e4
Create Date: 2026-11-12 10:01:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.mysql import BIGINT

# revision identifiers, used by Alembic.
revision: str = "a0b1c2d3e4f5"
down_revision: Union[str, Sequence[str], None] = "f9a0b1c2d3e4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TABLE_NAME = "df_engine_element_generations"


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        TABLE_NAME,
        sa.Column("id", BIGINT(unsigned=True), primary_key=True, autoincrement=True),
        sa.Column("element_id", BIGINT(unsigned=True), sa.ForeignKey("df_engine_elements.id"), nullable=False),
        sa.Column("generation_id", BIGINT(unsigned=True), sa.ForeignKey("df_engine_generations.id"), nullable=False),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table(TABLE_NAME)
