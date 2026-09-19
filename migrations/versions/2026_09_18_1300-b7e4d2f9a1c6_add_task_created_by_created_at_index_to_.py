"""add task_created_by_created_at index to df_engine_generations

Revision ID: b7e4d2f9a1c6
Revises: a3f9c1d7e2b8
Create Date: 2026-09-18 13:00:00.000000

"""

from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b7e4d2f9a1c6"
down_revision: Union[str, Sequence[str], None] = "a3f9c1d7e2b8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_index(
        "idx_generations_task_created_by_created_at",
        "df_engine_generations",
        ["task_id", "created_by", "created_at"],
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index("idx_generations_task_created_by_created_at", table_name="df_engine_generations")
