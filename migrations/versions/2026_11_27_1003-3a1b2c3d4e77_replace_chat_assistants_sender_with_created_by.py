"""replace df_engine_chat_assistants.sender with created_by

`created_by` is the user who wrote a `user` row; NULL for `assistant` and `system` rows. Existing user rows take the
creator of their chat session, the only user allowed to post in it.

Revision ID: 3a1b2c3d4e77
Revises: 3a1b2c3d4e76
Create Date: 2026-11-27 10:03:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql

# revision identifiers, used by Alembic.
revision: str = "3a1b2c3d4e77"
down_revision: Union[str, Sequence[str], None] = "3a1b2c3d4e76"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


TABLE_NAME = "df_engine_chat_assistants"
FK_NAME = "fk_df_engine_chat_assistants_created_by"


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(TABLE_NAME, sa.Column("created_by", mysql.BIGINT(unsigned=True), nullable=True))
    op.execute(
        f"UPDATE {TABLE_NAME} c JOIN df_engine_chat_sessions s ON s.id = c.session_id "
        "SET c.created_by = s.created_by WHERE c.role = 'user'"
    )
    op.create_foreign_key(FK_NAME, TABLE_NAME, "users", ["created_by"], ["id"])
    op.drop_column(TABLE_NAME, "sender")


def downgrade() -> None:
    """Downgrade schema. `sender` is rebuilt from the user's username, or 'openrouter' for non-user rows."""
    op.add_column(TABLE_NAME, sa.Column("sender", sa.String(255), nullable=True))
    op.execute(
        f"UPDATE {TABLE_NAME} c LEFT JOIN users u ON u.id = c.created_by "
        "SET c.sender = IF(c.role = 'user', COALESCE(u.username, 'user'), 'openrouter')"
    )
    op.alter_column(TABLE_NAME, "sender", existing_type=sa.String(255), nullable=False)
    op.drop_constraint(FK_NAME, TABLE_NAME, type_="foreignkey")
    op.drop_column(TABLE_NAME, "created_by")
