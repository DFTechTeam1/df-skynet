"""create df engine api snapshots

Revision ID: c21f4a9d8b3e
Revises: b10e09cd766e
Create Date: 2026-08-21 14:00:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.mysql import BIGINT, DECIMAL


# revision identifiers, used by Alembic.
revision: str = "c21f4a9d8b3e"
down_revision: Union[str, Sequence[str], None] = "b10e09cd766e"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "df_engine_api_snapshots",
        sa.Column("id", BIGINT(unsigned=True), primary_key=True, autoincrement=True),
        sa.Column("created_at", sa.DateTime, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime, nullable=True),
        sa.Column("expired_at", sa.DateTime, nullable=True),
        sa.Column("limit", DECIMAL(10, 2), nullable=True),
        sa.Column("limit_reset", sa.String(20), nullable=True),
        sa.Column("uid", sa.CHAR(36), nullable=False, unique=True),
        sa.Column("key", sa.String(255), nullable=False, unique=True),
        sa.Column("hash", sa.String(255), nullable=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column("employee_name", sa.String(255), nullable=True),
        sa.Column("created_by", BIGINT(unsigned=True), nullable=False),
        sa.Column("updated_by", BIGINT(unsigned=True), nullable=True),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table("df_engine_api_snapshots")
