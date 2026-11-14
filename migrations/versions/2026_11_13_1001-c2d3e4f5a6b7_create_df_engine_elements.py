"""create df_engine_elements

Revision ID: c2d3e4f5a6b7
Revises: f9a0b1c2d3e4
Create Date: 2026-11-13 10:01:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.mysql import BIGINT, LONGTEXT

# revision identifiers, used by Alembic.
revision: str = "c2d3e4f5a6b7"
down_revision: Union[str, Sequence[str], None] = "d264d1e38f12"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TABLE_NAME = "df_engine_elements"
ELEMENT_TYPES = sa.Enum("environment", "character", "object", "style", name="element_types")


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        TABLE_NAME,
        sa.Column("id", BIGINT(unsigned=True), primary_key=True, autoincrement=True),
        sa.Column("uid", sa.CHAR(36), nullable=False, unique=True),
        sa.Column("created_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime, nullable=True),
        sa.Column("types", ELEMENT_TYPES, nullable=True),
        sa.Column("name", sa.String(255), nullable=True),
        sa.Column("description", LONGTEXT, nullable=True),
        sa.Column(
            "task_id", BIGINT(unsigned=True), sa.ForeignKey("project_tasks.id", ondelete="SET NULL"), nullable=True
        ),
        sa.Column(
            "song_id",
            BIGINT(unsigned=True),
            sa.ForeignKey("project_song_lists.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("project_id", BIGINT(unsigned=True), sa.ForeignKey("projects.id"), nullable=True),
        sa.Column("created_by", BIGINT(unsigned=True), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("updated_by", BIGINT(unsigned=True), sa.ForeignKey("users.id"), nullable=True),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table(TABLE_NAME)
    ELEMENT_TYPES.drop(op.get_bind(), checkfirst=True)
