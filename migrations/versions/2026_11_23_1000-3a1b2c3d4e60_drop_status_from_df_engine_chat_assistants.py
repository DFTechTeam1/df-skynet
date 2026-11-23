"""drop status from df_engine_chat_assistants

Revision ID: 3a1b2c3d4e60
Revises: 3a1b2c3d4e5f
Create Date: 2026-11-23 10:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "3a1b2c3d4e60"
down_revision: Union[str, Sequence[str], None] = "3a1b2c3d4e5f"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TABLE_NAME = "df_engine_chat_assistants"
COLUMN_NAME = "status"

CHAT_ASSISTANT_STATUSES = sa.Enum("queued", "processing", "success", "failed", name="chat_assistant_statuses")


def upgrade() -> None:
    """Upgrade schema."""
    # A reply row is only written once its outcome is known, and `status_code` already carries it.
    op.drop_column(TABLE_NAME, COLUMN_NAME)


def downgrade() -> None:
    """Downgrade schema."""
    # Rows come back as `success`: the dropped values are not recoverable, and every stored row is already final.
    op.add_column(
        TABLE_NAME,
        sa.Column(COLUMN_NAME, CHAT_ASSISTANT_STATUSES, nullable=False, server_default="success"),
    )
