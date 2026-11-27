"""rename df_engine_chat_assistants.created_at to sent_at

Revision ID: 3a1b2c3d4e76
Revises: 3a1b2c3d4e75
Create Date: 2026-11-27 10:02:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "3a1b2c3d4e76"
down_revision: Union[str, Sequence[str], None] = "3a1b2c3d4e75"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


TABLE_NAME = "df_engine_chat_assistants"


def upgrade() -> None:
    """Upgrade schema. A rename keeps the stored values."""
    op.alter_column(
        TABLE_NAME, "created_at", new_column_name="sent_at", existing_type=sa.DateTime(), existing_nullable=False
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.alter_column(
        TABLE_NAME, "sent_at", new_column_name="created_at", existing_type=sa.DateTime(), existing_nullable=False
    )
