"""rename df_engine_openrouter_logs to df_engine_external_api_calls

- rename table so it can hold call logs for any external integration (not just OpenRouter)
- add type varchar(255) NOT NULL DEFAULT 'openrouter' to discriminate rows (e.g. "udin")
- re-prefix the 3 index names to match the new table name

Revision ID: b5da41b87763
Revises: 30914ac4bc93
Create Date: 2026-09-12 15:00:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "b5da41b87763"
down_revision: Union[str, Sequence[str], None] = "30914ac4bc93"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

OLD_NAME = "df_engine_openrouter_logs"
NEW_NAME = "df_engine_external_api_calls"

OLD_INDEXES = (
    "idx_df_engine_openrouter_logs_created_at_id",
    "idx_openrouter_logs_generation_attempt",
    "idx_openrouter_logs_response_status",
)
NEW_INDEXES = (
    ("idx_df_engine_external_api_calls_created_at_id", ["created_at", "id"]),
    ("idx_external_api_calls_generation_attempt", ["generation_id", "attempt"]),
    ("idx_external_api_calls_response_status", ["response_status_code"]),
)


def upgrade() -> None:
    """Upgrade schema."""
    op.rename_table(OLD_NAME, NEW_NAME)
    op.add_column(
        NEW_NAME,
        sa.Column("type", sa.String(255), nullable=False, server_default=sa.text("'openrouter'")),
    )

    # generation_id/attempt's index backs an FK constraint — MySQL refuses to drop
    # it unless a replacement index already exists, so create-then-drop, not the reverse.
    for old_name, (new_name, columns) in zip(OLD_INDEXES, NEW_INDEXES):
        op.create_index(new_name, NEW_NAME, columns)
        op.drop_index(old_name, table_name=NEW_NAME)


def downgrade() -> None:
    """Downgrade schema."""
    for old_name, (new_name, columns) in zip(OLD_INDEXES, NEW_INDEXES):
        op.create_index(old_name, NEW_NAME, columns)
        op.drop_index(new_name, table_name=NEW_NAME)

    op.drop_column(NEW_NAME, "type")
    op.rename_table(NEW_NAME, OLD_NAME)
