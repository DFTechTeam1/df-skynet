"""create df_engine_upload_files

Revision ID: e5a6c7d8f9b0
Revises: d4f5b6c7e8a9
Create Date: 2026-09-10 14:10:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.mysql import BIGINT


# revision identifiers, used by Alembic.
revision: str = "e5a6c7d8f9b0"
down_revision: Union[str, Sequence[str], None] = "d4f5b6c7e8a9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TABLE_NAME = "df_engine_upload_files"
UPLOAD_FILE_TYPES = sa.Enum("video", "image", name="upload_file_types")


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        TABLE_NAME,
        sa.Column("id", BIGINT(unsigned=True), primary_key=True, autoincrement=True),
        sa.Column("created_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime, nullable=True),
        sa.Column("uid", sa.CHAR(36), nullable=False, unique=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("type", UPLOAD_FILE_TYPES, nullable=False, server_default="image"),
        sa.Column("path", sa.Text, nullable=False),
        sa.Column("md5", sa.String(255), nullable=True),
        sa.Column("size", sa.BigInteger, nullable=False),
        sa.Column("project_id", BIGINT(unsigned=True), sa.ForeignKey("projects.id"), nullable=False),
        sa.Column("created_by", BIGINT(unsigned=True), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("updated_by", BIGINT(unsigned=True), sa.ForeignKey("users.id"), nullable=True),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table(TABLE_NAME)
    UPLOAD_FILE_TYPES.drop(op.get_bind(), checkfirst=True)
