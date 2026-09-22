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
    op.create_index("idx_generations_kind", TABLE_NAME, ["kind"])
    op.create_index("idx_generations_kind_created_by", TABLE_NAME, ["kind", "created_by"])
    op.create_index("idx_generations_status_created_at", TABLE_NAME, ["status", "created_at"])
    op.create_index("idx_generations_sourceable", TABLE_NAME, ["sourceable_id", "sourceable_type"])
    op.create_index("idx_generations_created_at", TABLE_NAME, ["created_at"])
    op.create_index("idx_generations_project_task", TABLE_NAME, ["project_id", "task_id"])
    op.drop_index("idx_generations_project_id", table_name=TABLE_NAME)
    op.alter_column(TABLE_NAME, "response", existing_type=sa.Text(), type_=sa.JSON(), existing_nullable=True)
