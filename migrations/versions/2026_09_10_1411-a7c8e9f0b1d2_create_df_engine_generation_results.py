"""create df_engine_generation_results

Revision ID: a7c8e9f0b1d2
Revises: e5a6c7d8f9b0
Create Date: 2026-09-10 14:11:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.mysql import BIGINT


# revision identifiers, used by Alembic.
revision: str = "a7c8e9f0b1d2"
down_revision: Union[str, Sequence[str], None] = "e5a6c7d8f9b0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TABLE_NAME = "df_engine_generation_results"


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        TABLE_NAME,
        sa.Column("id", BIGINT(unsigned=True), primary_key=True, autoincrement=True),
        sa.Column("uid", sa.CHAR(36), nullable=False, unique=True),
        sa.Column("created_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime, nullable=True),
        sa.Column("archieved_at", sa.DateTime, nullable=True),
        sa.Column("generation_id", BIGINT(unsigned=True), sa.ForeignKey("df_engine_generations.id"), nullable=True),
        sa.Column("parent_id", BIGINT(unsigned=True), sa.ForeignKey("df_engine_generation_results.id"), nullable=True),
        sa.Column("md5", sa.String(255), nullable=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("path", sa.Text, nullable=False),
        sa.Column("size", sa.BigInteger, nullable=False),
        sa.Column("is_main", sa.Boolean, nullable=False, server_default=sa.true()),
        sa.Column("is_favourite", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("created_by", BIGINT(unsigned=True), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("updated_by", BIGINT(unsigned=True), sa.ForeignKey("users.id"), nullable=True),
    )
    op.create_index("idx_generation_results_generation_id", TABLE_NAME, ["generation_id"])
    op.create_index("idx_generation_results_parent_id", TABLE_NAME, ["parent_id"])


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table(TABLE_NAME)
