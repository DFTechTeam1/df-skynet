"""add index df engine openrouter logs created_at id

Revision ID: a3d7f1c9b204
Revises: 8c12f91c237c
Create Date: 2026-08-27 12:00:00.000000

"""

from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = "a3d7f1c9b204"
down_revision: Union[str, Sequence[str], None] = "8c12f91c237c"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

INDEX_NAME = "ix_df_engine_openrouter_logs_created_at_id"
TABLE_NAME = "df_engine_openrouter_logs"


def upgrade() -> None:
    """Serve `ORDER BY created_at DESC, id DESC` from an index so paging the logs
    never filesorts the table's large JSON columns (MySQL error 1038)."""
    op.create_index(INDEX_NAME, TABLE_NAME, ["created_at", "id"])


def downgrade() -> None:
    op.drop_index(INDEX_NAME, table_name=TABLE_NAME)
