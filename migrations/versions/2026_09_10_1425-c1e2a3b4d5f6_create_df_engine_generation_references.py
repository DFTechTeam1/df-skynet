"""create df_engine_generation_references

Revision ID: c1e2a3b4d5f6
Revises: b0d1f2a3c4e5
Create Date: 2026-09-10 14:25:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.mysql import BIGINT


# revision identifiers, used by Alembic.
revision: str = "c1e2a3b4d5f6"
down_revision: Union[str, Sequence[str], None] = "b0d1f2a3c4e5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TABLE_NAME = "df_engine_generation_references"


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        TABLE_NAME,
        sa.Column("id", BIGINT(unsigned=True), primary_key=True, autoincrement=True),
        sa.Column("created_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
        sa.Column("generation_id", BIGINT(unsigned=True), sa.ForeignKey("df_engine_generations.id"), nullable=False),
        sa.Column("result_id", BIGINT(unsigned=True), sa.ForeignKey("df_engine_generation_results.id"), nullable=False),
    )
    op.create_index("idx_generation_references_generation_id", TABLE_NAME, ["generation_id"])
    op.create_index("idx_generation_references_result_id", TABLE_NAME, ["result_id"])
    op.create_index("idx_generation_references_unique_pair", TABLE_NAME, ["generation_id", "result_id"], unique=True)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table(TABLE_NAME)
