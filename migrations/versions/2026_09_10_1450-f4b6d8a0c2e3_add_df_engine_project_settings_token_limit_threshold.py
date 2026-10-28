"""add df_engine_project_settings.token_limit_threshold

Per-project override of the token-limit warning fraction (0-1), nullable.
NULL = inherit the project class's value from admin_setting.project_class_limitations.

Revision ID: f4b6d8a0c2e3
Revises: d2f4a6b8c0e1
Create Date: 2026-09-10 14:50:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "f4b6d8a0c2e3"
down_revision: Union[str, Sequence[str], None] = "d2f4a6b8c0e1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TABLE_NAME = "df_engine_project_settings"


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(TABLE_NAME, sa.Column("token_limit_threshold", sa.Float, nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column(TABLE_NAME, "token_limit_threshold")
