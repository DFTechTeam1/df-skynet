"""rename expired_at to expires_at on df_engine_api_keys

Revision ID: 66edc357575a
Revises: d4a1b2c3e4f5
Create Date: 2026-08-22 07:53:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "66edc357575a"
down_revision: Union[str, Sequence[str], None] = "d4a1b2c3e4f5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.alter_column(
        "df_engine_api_keys",
        "expired_at",
        new_column_name="expires_at",
        existing_type=sa.DateTime(),
        existing_nullable=True,
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.alter_column(
        "df_engine_api_keys",
        "expires_at",
        new_column_name="expired_at",
        existing_type=sa.DateTime(),
        existing_nullable=True,
    )
