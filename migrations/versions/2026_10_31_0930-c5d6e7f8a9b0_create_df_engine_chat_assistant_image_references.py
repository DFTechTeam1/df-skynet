"""create df_engine_chat_assistant_image_references

Revision ID: c5d6e7f8a9b0
Revises: a9b8c7d6e5f4
Create Date: 2026-10-31 09:30:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.mysql import BIGINT

# revision identifiers, used by Alembic.
revision: str = "c5d6e7f8a9b0"
down_revision: Union[str, Sequence[str], None] = "a9b8c7d6e5f4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TABLE_NAME = "df_engine_chat_assistant_image_references"


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        TABLE_NAME,
        sa.Column("id", BIGINT(unsigned=True), primary_key=True, autoincrement=True),
        sa.Column(
            "chat_id",
            BIGINT(unsigned=True),
            sa.ForeignKey("df_engine_chat_assistants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "generation_id",
            BIGINT(unsigned=True),
            sa.ForeignKey("df_engine_generations.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column("path", sa.String(512), nullable=False),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table(TABLE_NAME)
