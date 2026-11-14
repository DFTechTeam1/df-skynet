"""create df_engine_element_uploads and move element uploads into it

Revision ID: e1a2b3c4d5f6
Revises: 80e44973dbd4
Create Date: 2026-11-14 11:00:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.mysql import BIGINT

# revision identifiers, used by Alembic.
revision: str = "e1a2b3c4d5f6"
down_revision: Union[str, Sequence[str], None] = "80e44973dbd4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TABLE_NAME = "df_engine_element_uploads"
COLUMNS = "uid, created_at, updated_at, name, path, md5, size, element_id, project_id, created_by, updated_by"


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        TABLE_NAME,
        sa.Column("id", BIGINT(unsigned=True), primary_key=True, autoincrement=True),
        sa.Column("uid", sa.CHAR(36), nullable=False, unique=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("path", sa.Text(), nullable=False),
        sa.Column("md5", sa.String(255), nullable=True),
        sa.Column("size", sa.BigInteger(), nullable=False),
        sa.Column("element_id", BIGINT(unsigned=True), sa.ForeignKey("df_engine_elements.id"), nullable=False),
        sa.Column("project_id", BIGINT(unsigned=True), sa.ForeignKey("projects.id"), nullable=False),
        sa.Column("created_by", BIGINT(unsigned=True), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("updated_by", BIGINT(unsigned=True), sa.ForeignKey("users.id"), nullable=True),
    )
    # element uploads used to live in df_engine_upload_files: move them over before element_id is dropped
    op.execute(
        f"INSERT INTO {TABLE_NAME} ({COLUMNS}) "
        f"SELECT {COLUMNS} FROM df_engine_upload_files WHERE element_id IS NOT NULL"
    )
    op.execute("DELETE FROM df_engine_upload_files WHERE element_id IS NOT NULL")


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table(TABLE_NAME)
