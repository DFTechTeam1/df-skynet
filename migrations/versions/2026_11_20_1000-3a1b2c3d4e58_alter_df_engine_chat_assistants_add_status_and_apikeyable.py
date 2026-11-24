"""alter df_engine_chat_assistants: add status + apikeyable, status_code nullable

Revision ID: 3a1b2c3d4e58
Revises: 3a1b2c3d4e57
Create Date: 2026-11-20 10:00:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.mysql import BIGINT

# revision identifiers, used by Alembic.
revision: str = "3a1b2c3d4e58"
down_revision: Union[str, Sequence[str], None] = "3a1b2c3d4e57"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


TABLE_NAME = "df_engine_chat_assistants"
INDEX_NAME = "idx_chat_assistants_apikeyable"

CHAT_ASSISTANT_STATUSES = sa.Enum("queued", "processing", "success", "failed", name="chat_assistant_statuses")


def upgrade() -> None:
    """Upgrade schema."""
    # Existing rows (and system/user rows) are already final, so they default to `success`.
    op.add_column(
        TABLE_NAME,
        sa.Column("status", CHAT_ASSISTANT_STATUSES, nullable=False, server_default="success"),
    )
    # Polymorphic: apikeyable_type is the model class name (DfEngineApiKeys | DfEngineApiKeySnapshots), so no FK.
    op.add_column(TABLE_NAME, sa.Column("apikeyable_id", BIGINT(unsigned=True), nullable=True))
    op.add_column(TABLE_NAME, sa.Column("apikeyable_type", sa.String(255), nullable=True))
    op.create_index(INDEX_NAME, TABLE_NAME, ["apikeyable_type", "apikeyable_id"])
    # System/user rows have no completion, so no status code.
    op.alter_column(
        TABLE_NAME,
        "status_code",
        existing_type=sa.Integer,
        nullable=True,
        existing_server_default="200",
        server_default=None,
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.execute(f"UPDATE {TABLE_NAME} SET status_code = 200 WHERE status_code IS NULL")
    op.alter_column(
        TABLE_NAME,
        "status_code",
        existing_type=sa.Integer,
        nullable=False,
        server_default="200",
    )
    op.drop_index(INDEX_NAME, table_name=TABLE_NAME)
    op.drop_column(TABLE_NAME, "apikeyable_type")
    op.drop_column(TABLE_NAME, "apikeyable_id")
    op.drop_column(TABLE_NAME, "status")
