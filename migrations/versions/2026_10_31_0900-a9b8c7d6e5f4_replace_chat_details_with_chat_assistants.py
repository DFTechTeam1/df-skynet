"""replace df_engine_chat_details with df_engine_chat_assistants

Revision ID: a9b8c7d6e5f4
Revises: d3f1a9c27b64
Create Date: 2026-10-31 09:00:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.mysql import BIGINT

# revision identifiers, used by Alembic.
revision: str = "a9b8c7d6e5f4"
down_revision: Union[str, Sequence[str], None] = "d3f1a9c27b64"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.drop_table("df_engine_chat_details")
    op.create_table(
        "df_engine_chat_assistants",
        sa.Column("id", BIGINT(unsigned=True), primary_key=True, autoincrement=True),
        sa.Column("uid", sa.CHAR(36), nullable=False, unique=True),
        sa.Column("placeholder", sa.Text(length=4294967295), nullable=False),
        sa.Column("created_by", BIGINT(unsigned=True), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("created_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
        sa.Column(
            "updated_at",
            sa.DateTime,
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP"),
        ),
        sa.Column("archived_at", sa.DateTime, nullable=True),
    )
    op.create_index(
        "idx_chat_assistants_created_by_archived_at", "df_engine_chat_assistants", ["created_by", "archived_at"]
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table("df_engine_chat_assistants")
    op.create_table(
        "df_engine_chat_details",
        sa.Column("id", BIGINT(unsigned=True), primary_key=True, autoincrement=True),
        sa.Column("generation_id", BIGINT(unsigned=True), sa.ForeignKey("df_engine_generations.id"), nullable=False),
        sa.Column("parent_id", BIGINT(unsigned=True), sa.ForeignKey("df_engine_generations.id"), nullable=True),
    )
    op.create_index("idx_chat_details_parent_id", "df_engine_chat_details", ["parent_id"])
