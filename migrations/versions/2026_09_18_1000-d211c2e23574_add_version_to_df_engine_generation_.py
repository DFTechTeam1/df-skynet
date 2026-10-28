"""add version to df engine generation results

Revision ID: d211c2e23574
Revises: e9d8c7b6a5f4
Create Date: 2026-09-18 10:00:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "d211c2e23574"
down_revision: Union[str, Sequence[str], None] = "e9d8c7b6a5f4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        "df_engine_generation_results",
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("df_engine_generation_results", "version")
