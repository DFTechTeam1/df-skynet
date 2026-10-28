"""rename expired_at to expires_at on df_engine_api_snapshots, add employee_id

Revision ID: a0b404a3d8dd
Revises: 66edc357575a
Create Date: 2026-08-22 07:54:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.mysql import BIGINT


# revision identifiers, used by Alembic.
revision: str = "a0b404a3d8dd"
down_revision: Union[str, Sequence[str], None] = "66edc357575a"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.alter_column(
        "df_engine_api_snapshots",
        "expired_at",
        new_column_name="expires_at",
        existing_type=sa.DateTime(),
        existing_nullable=True,
    )
    op.add_column(
        "df_engine_api_snapshots",
        sa.Column("employee_id", BIGINT(unsigned=True), nullable=True),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("df_engine_api_snapshots", "employee_id")
    op.alter_column(
        "df_engine_api_snapshots",
        "expires_at",
        new_column_name="expired_at",
        existing_type=sa.DateTime(),
        existing_nullable=True,
    )
