"""create df_engine_queues

Revision ID: a9c0e1f2b3d4
Revises: f8b9d0e1a2c3
Create Date: 2026-09-10 14:23:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.mysql import BIGINT


# revision identifiers, used by Alembic.
revision: str = "a9c0e1f2b3d4"
down_revision: Union[str, Sequence[str], None] = "f8b9d0e1a2c3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TABLE_NAME = "df_engine_queues"
QUEUE_EVENT_TYPES = sa.Enum(
    "enqueued",
    "started",
    "retried",
    "succeeded",
    "failed",
    name="queue_event_types",
)


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        TABLE_NAME,
        sa.Column("id", BIGINT(unsigned=True), primary_key=True, autoincrement=True),
        sa.Column("created_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
        sa.Column("task_uid", sa.String(36), nullable=False),
        sa.Column("generation_id", BIGINT(unsigned=True), sa.ForeignKey("df_engine_generations.id"), nullable=True),
        sa.Column("queue_name", sa.String(255), nullable=False),
        sa.Column("event_type", QUEUE_EVENT_TYPES, nullable=False),
        sa.Column("attempt", sa.Integer, nullable=False, server_default="1"),
        sa.Column("detail", sa.JSON, nullable=True),
    )
    op.create_index("idx_queues_task_uid", TABLE_NAME, ["task_uid"])
    op.create_index("idx_queues_generation_event", TABLE_NAME, ["generation_id", "event_type"])
    op.create_index("idx_queues_queue_event", TABLE_NAME, ["queue_name", "event_type"])
    op.create_index("idx_queues_generation_created_at", TABLE_NAME, ["generation_id", "created_at"])


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table(TABLE_NAME)
    QUEUE_EVENT_TYPES.drop(op.get_bind(), checkfirst=True)
