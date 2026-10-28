"""drop df_engine_project_settings.concurent_generations

Concurrency is configured internally now, not per-project.

Revision ID: d4f5b6c7e8a9
Revises: c3e4a5b6d7f8
Create Date: 2026-09-10 14:03:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "d4f5b6c7e8a9"
down_revision: Union[str, Sequence[str], None] = "c3e4a5b6d7f8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TABLE_NAME = "df_engine_project_settings"


def upgrade() -> None:
    """Upgrade schema."""
    op.drop_column(TABLE_NAME, "concurent_generations")


def downgrade() -> None:
    """Downgrade schema."""
    op.add_column(
        TABLE_NAME,
        sa.Column("concurent_generations", sa.Integer, nullable=False, server_default="0"),
    )
    op.alter_column(
        TABLE_NAME,
        "concurent_generations",
        server_default=None,
        existing_type=sa.Integer,
        existing_nullable=False,
    )
