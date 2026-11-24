"""drop df_engine_chat_assistant_image_references

Revision ID: 3a1b2c3d4e53
Revises: 3a1b2c3d4e52
Create Date: 2026-11-18 10:02:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.mysql import BIGINT

# revision identifiers, used by Alembic.
revision: str = "3a1b2c3d4e53"
down_revision: Union[str, Sequence[str], None] = "3a1b2c3d4e52"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


TABLE_NAME = "df_engine_chat_assistant_image_references"


def upgrade() -> None:
    """Upgrade schema."""
    op.drop_table(TABLE_NAME)


def downgrade() -> None:
    """Downgrade schema."""
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
