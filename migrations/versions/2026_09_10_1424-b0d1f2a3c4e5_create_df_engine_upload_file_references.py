"""create df_engine_upload_file_references

Revision ID: b0d1f2a3c4e5
Revises: a9c0e1f2b3d4
Create Date: 2026-09-10 14:24:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.mysql import BIGINT


# revision identifiers, used by Alembic.
revision: str = "b0d1f2a3c4e5"
down_revision: Union[str, Sequence[str], None] = "a9c0e1f2b3d4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TABLE_NAME = "df_engine_upload_file_references"


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        TABLE_NAME,
        sa.Column("id", BIGINT(unsigned=True), primary_key=True, autoincrement=True),
        sa.Column("created_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
        sa.Column("generation_id", BIGINT(unsigned=True), sa.ForeignKey("df_engine_generations.id"), nullable=False),
        sa.Column("file_id", BIGINT(unsigned=True), sa.ForeignKey("df_engine_upload_files.id"), nullable=False),
    )
    op.create_index("idx_upload_file_references_generation_id", TABLE_NAME, ["generation_id"])
    op.create_index("idx_upload_file_references_file_id", TABLE_NAME, ["file_id"])
    op.create_index("idx_upload_file_references_unique_pair", TABLE_NAME, ["generation_id", "file_id"], unique=True)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table(TABLE_NAME)
