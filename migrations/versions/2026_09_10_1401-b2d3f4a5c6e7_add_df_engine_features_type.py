"""add df_engine_features.type

Revision ID: b2d3f4a5c6e7
Revises: a1c2e3f4b5d6
Create Date: 2026-09-10 14:01:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "b2d3f4a5c6e7"
down_revision: Union[str, Sequence[str], None] = "a1c2e3f4b5d6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TABLE_NAME = "df_engine_features"


def upgrade() -> None:
    """Upgrade schema."""
    # Added NOT NULL on a possibly-populated table: backfill existing rows with
    # '' via a temporary server_default, then drop the default to match the DBML.
    op.add_column(
        TABLE_NAME,
        sa.Column("type", sa.String(255), nullable=False, server_default=sa.text("''")),
    )
    op.alter_column(TABLE_NAME, "type", server_default=None, existing_type=sa.String(255), existing_nullable=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column(TABLE_NAME, "type")
