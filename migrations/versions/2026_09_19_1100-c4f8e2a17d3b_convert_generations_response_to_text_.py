"""convert df_engine_generations.response to text and trim unused indexes

Revision ID: c4f8e2a17d3b
Revises: d8f2a4c6e1b3
Create Date: 2026-09-19 11:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c4f8e2a17d3b"
down_revision: Union[str, Sequence[str], None] = "d8f2a4c6e1b3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TABLE_NAME = "df_engine_generations"


def upgrade() -> None:
    """Upgrade schema."""
    op.alter_column(TABLE_NAME, "response", existing_type=sa.JSON(), type_=sa.Text(), existing_nullable=True)
    op.create_index("idx_generations_project_id", TABLE_NAME, ["project_id"])
    op.drop_index("idx_generations_project_task", table_name=TABLE_NAME)
    op.drop_index("idx_generations_kind", table_name=TABLE_NAME)
    op.drop_index("idx_generations_kind_created_by", table_name=TABLE_NAME)
    op.drop_index("idx_generations_status_created_at", table_name=TABLE_NAME)
    op.drop_index("idx_generations_sourceable", table_name=TABLE_NAME)
    op.drop_index("idx_generations_created_at", table_name=TABLE_NAME)


def downgrade() -> None:
    """Downgrade schema."""
    # idempotent: non-transactional MySQL DDL means a retried downgrade can
    # find some of these already (re)created by a prior partial run, or
    # already FK-protected (idx_generations_project_task backs project_id's
    # FK, so MySQL refuses to drop it — it just needs to stay, which it does).
    existing = {ix["name"] for ix in sa.inspect(op.get_bind()).get_indexes(TABLE_NAME)}
    for name, cols in (
        ("idx_generations_kind", ["kind"]),
        ("idx_generations_kind_created_by", ["kind", "created_by"]),
        ("idx_generations_status_created_at", ["status", "created_at"]),
        ("idx_generations_sourceable", ["sourceable_id", "sourceable_type"]),
        ("idx_generations_created_at", ["created_at"]),
        ("idx_generations_project_task", ["project_id", "task_id"]),
    ):
        if name not in existing:
            op.create_index(name, TABLE_NAME, cols)
    if "idx_generations_project_id" in existing:
        op.drop_index("idx_generations_project_id", table_name=TABLE_NAME)
    # ponytail: converting back to JSON is lossy once any row holds non-JSON
    # text (base64 payloads, plain strings) — MySQL rejects rows that aren't
    # valid JSON instead of coercing them, so the column stays TEXT.
