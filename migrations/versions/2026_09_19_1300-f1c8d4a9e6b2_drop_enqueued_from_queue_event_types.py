"""drop enqueued from queue_event_types

- unused: nothing ever writes an 'enqueued' event, only the GenerationTask
  hooks (started/retried/succeeded/failed) write to df_engine_queues

Revision ID: f1c8d4a9e6b2
Revises: e5a7f3c9b2d1
Create Date: 2026-09-19 13:00:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "f1c8d4a9e6b2"
down_revision: Union[str, Sequence[str], None] = "e5a7f3c9b2d1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TABLE_NAME = "df_engine_queues"

OLD_EVENT_TYPES = ("enqueued", "started", "retried", "succeeded", "failed")
NEW_EVENT_TYPES = ("started", "retried", "succeeded", "failed")


def upgrade() -> None:
    """Upgrade schema."""
    op.alter_column(
        TABLE_NAME,
        "event_type",
        existing_type=sa.Enum(*OLD_EVENT_TYPES, name="queue_event_types"),
        type_=sa.Enum(*NEW_EVENT_TYPES, name="queue_event_types"),
        existing_nullable=False,
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.alter_column(
        TABLE_NAME,
        "event_type",
        existing_type=sa.Enum(*NEW_EVENT_TYPES, name="queue_event_types"),
        type_=sa.Enum(*OLD_EVENT_TYPES, name="queue_event_types"),
        existing_nullable=False,
    )
