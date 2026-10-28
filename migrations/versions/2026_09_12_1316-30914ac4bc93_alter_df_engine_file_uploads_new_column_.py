"""alter df engine file uploads new column task id

Revision ID: 30914ac4bc93
Revises: 17e8cc4fb42d
Create Date: 2026-09-12 13:16:15.129092

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.mysql import BIGINT


# revision identifiers, used by Alembic.
revision: str = "30914ac4bc93"
down_revision: Union[str, Sequence[str], None] = "17e8cc4fb42d"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TABLE_NAME = "df_engine_upload_files"
FK_NAME = "fk_df_engine_upload_files_task_id"


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(TABLE_NAME, sa.Column("task_id", BIGINT(unsigned=True), nullable=True))
    op.create_foreign_key(FK_NAME, TABLE_NAME, "project_tasks", ["task_id"], ["id"])


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_constraint(FK_NAME, TABLE_NAME, type_="foreignkey")
    op.drop_column(TABLE_NAME, "task_id")
