"""create df_engine_chat_details

Revision ID: f2b3d4e5a6c7
Revises: e1a2c3d4f5b6
Create Date: 2026-09-10 14:16:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.mysql import BIGINT


# revision identifiers, used by Alembic.
revision: str = "f2b3d4e5a6c7"
down_revision: Union[str, Sequence[str], None] = "e1a2c3d4f5b6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TABLE_NAME = "df_engine_chat_details"


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        TABLE_NAME,
        sa.Column("id", BIGINT(unsigned=True), primary_key=True, autoincrement=True),
        sa.Column("generation_id", BIGINT(unsigned=True), sa.ForeignKey("df_engine_generations.id"), nullable=False),
        sa.Column("parent_id", BIGINT(unsigned=True), sa.ForeignKey("df_engine_generations.id"), nullable=True),
    )
    op.create_index("idx_chat_details_parent_id", TABLE_NAME, ["parent_id"])


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table(TABLE_NAME)
