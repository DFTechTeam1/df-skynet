"""create df_engine_chat_references

Revision ID: 3a1b2c3d4e56
Revises: 3a1b2c3d4e55
Create Date: 2026-11-18 10:05:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.mysql import BIGINT

# revision identifiers, used by Alembic.
revision: str = "3a1b2c3d4e56"
down_revision: Union[str, Sequence[str], None] = "3a1b2c3d4e55"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


TABLE_NAME = "df_engine_chat_references"


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        TABLE_NAME,
        sa.Column("id", BIGINT(unsigned=True), primary_key=True, autoincrement=True),
        sa.Column("chat_id", BIGINT(unsigned=True), sa.ForeignKey("df_engine_chat_assistants.id"), nullable=False),
        sa.Column(
            "attachment_id", BIGINT(unsigned=True), sa.ForeignKey("df_engine_chat_attachments.id"), nullable=False
        ),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table(TABLE_NAME)
