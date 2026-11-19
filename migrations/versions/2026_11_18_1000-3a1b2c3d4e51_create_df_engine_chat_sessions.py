"""create df_engine_chat_sessions

Revision ID: 3a1b2c3d4e51
Revises: f9a0b1c2d3e4
Create Date: 2026-11-18 10:00:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.mysql import BIGINT

# revision identifiers, used by Alembic.
revision: str = "3a1b2c3d4e51"
down_revision: Union[str, Sequence[str], None] = "f9a0b1c2d3e4"
branch_labels: Union[str, Sequence[str], None] = ("feat_chat_assistant",)
depends_on: Union[str, Sequence[str], None] = None


TABLE_NAME = "df_engine_chat_sessions"


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        TABLE_NAME,
        sa.Column("id", BIGINT(unsigned=True), primary_key=True, autoincrement=True),
        sa.Column("created_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
        sa.Column(
            "updated_at",
            sa.DateTime,
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP"),
        ),
        sa.Column("uid", sa.CHAR(36), nullable=False, unique=True),
        sa.Column("topic", sa.String(255), nullable=False),
        sa.Column("menu_id", BIGINT(unsigned=True), sa.ForeignKey("df_engine_menus.id"), nullable=False),
        sa.Column("feature_id", BIGINT(unsigned=True), sa.ForeignKey("df_engine_features.id"), nullable=False),
        sa.Column("project_id", BIGINT(unsigned=True), sa.ForeignKey("projects.id"), nullable=False),
        sa.Column("created_by", BIGINT(unsigned=True), sa.ForeignKey("users.id"), nullable=False),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table(TABLE_NAME)
