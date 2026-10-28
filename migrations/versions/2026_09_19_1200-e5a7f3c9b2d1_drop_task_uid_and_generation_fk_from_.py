"""drop task_uid and generation_id fk from df_engine_queues

- this is a pure logging table; generation_id stays as a plain column
  (no FK) so a deleted/reconciled generation never blocks writing a log row
- task_uid (the Celery task id) isn't queried anywhere in the codebase

Revision ID: e5a7f3c9b2d1
Revises: c4f8e2a17d3b
Create Date: 2026-09-19 12:00:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "e5a7f3c9b2d1"
down_revision: Union[str, Sequence[str], None] = "c4f8e2a17d3b"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TABLE = "df_engine_queues"
FK_NAME = "df_engine_queues_ibfk_1"
TASK_UID_INDEX = "idx_queues_task_uid"


def upgrade() -> None:
    """Upgrade schema."""
    op.drop_constraint(FK_NAME, TABLE, type_="foreignkey")
    op.drop_index(TASK_UID_INDEX, table_name=TABLE)
    op.drop_column(TABLE, "task_uid")


def downgrade() -> None:
    """Downgrade schema."""
    op.add_column(TABLE, sa.Column("task_uid", sa.String(36), nullable=False, server_default=""))
    op.create_index(TASK_UID_INDEX, TABLE, ["task_uid"])
    op.create_foreign_key(FK_NAME, TABLE, "df_engine_generations", ["generation_id"], ["id"])
