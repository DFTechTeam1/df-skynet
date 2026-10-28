"""create df engine settings

Revision ID: 59394da59379
Revises: 16d4ca9e7038
Create Date: 2026-08-25 13:52:27.513886

"""

from typing import Sequence, Union
from sqlalchemy.dialects.mysql import BIGINT
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "59394da59379"
down_revision: Union[str, Sequence[str], None] = "16d4ca9e7038"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "df_engine_settings",
        sa.Column("id", BIGINT(unsigned=True), primary_key=True, autoincrement=True),
        sa.Column("created_at", sa.DateTime, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime, nullable=True),
        sa.Column("key", sa.String(255), nullable=True),
        sa.Column("value", sa.Text, nullable=True),
        sa.Column("code", sa.String(255), nullable=True),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table("df_engine_settings")
