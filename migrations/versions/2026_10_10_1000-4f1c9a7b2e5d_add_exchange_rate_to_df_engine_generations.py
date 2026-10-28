"""add_exchange_rate_to_df_engine_generations

Revision ID: 4f1c9a7b2e5d
Revises: 7b92fbeae9f2
Create Date: 2026-10-10 10:00:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "4f1c9a7b2e5d"
down_revision: Union[str, Sequence[str], None] = "7b92fbeae9f2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TABLE_NAME = "df_engine_generations"


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        TABLE_NAME,
        sa.Column("exchange_rate", sa.DECIMAL(20, 8), nullable=False, server_default="0"),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column(TABLE_NAME, "exchange_rate")
