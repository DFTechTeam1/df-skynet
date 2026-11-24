"""add archieved_at to df_engine_chat_sessions

Revision ID: 3a1b2c3d4e5f
Revises: 3a1b2c3d4e5e
Create Date: 2026-11-21 10:01:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "3a1b2c3d4e5f"
down_revision: Union[str, Sequence[str], None] = "3a1b2c3d4e5e"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TABLE_NAME = "df_engine_chat_sessions"


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(TABLE_NAME, sa.Column("archieved_at", sa.DateTime(), nullable=True, server_default=None))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column(TABLE_NAME, "archieved_at")
