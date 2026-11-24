"""add unique message_id to chat_assistants and guardrail_validations (idempotent queue consumer)

Revision ID: 3a1b2c3d4e70
Revises: 3a1b2c3d4e64
Create Date: 2026-11-24 14:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "3a1b2c3d4e70"
down_revision: Union[str, Sequence[str], None] = "3a1b2c3d4e64"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TABLES = ("df_engine_chat_assistants", "df_engine_guardrail_validations")


def upgrade() -> None:
    """Upgrade schema."""
    for table in TABLES:
        op.add_column(table, sa.Column("message_id", sa.CHAR(36), nullable=True))
        op.create_unique_constraint(f"uq_{table}_message_id", table, ["message_id"])


def downgrade() -> None:
    """Downgrade schema."""
    for table in TABLES:
        op.drop_constraint(f"uq_{table}_message_id", table, type_="unique")
        op.drop_column(table, "message_id")
