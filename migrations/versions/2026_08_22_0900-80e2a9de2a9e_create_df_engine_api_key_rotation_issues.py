"""create df engine api key rotation issues

Revision ID: 80e2a9de2a9e
Revises: a0b404a3d8dd
Create Date: 2026-08-22 09:00:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.mysql import BIGINT


# revision identifiers, used by Alembic.
revision: str = "80e2a9de2a9e"
down_revision: Union[str, Sequence[str], None] = "a0b404a3d8dd"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "df_engine_api_key_rotation_issues",
        sa.Column("id", BIGINT(unsigned=True), primary_key=True, autoincrement=True),
        sa.Column("created_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
        sa.Column("uid", sa.CHAR(36), nullable=False, unique=True),
        sa.Column("old_uid", sa.CHAR(36), nullable=False),
        sa.Column("new_uid", sa.CHAR(36), nullable=True),
        sa.Column("new_key_hash", sa.String(255), nullable=True),
        sa.Column("new_key_value", sa.String(255), nullable=True),
        sa.Column("issue_type", sa.String(50), nullable=False),
        sa.Column("detail", sa.Text, nullable=True),
        sa.Column("resolved_at", sa.DateTime, nullable=True),
    )
    op.create_index(
        "ix_df_engine_api_key_rotation_issues_unresolved",
        "df_engine_api_key_rotation_issues",
        ["resolved_at"],
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(
        "ix_df_engine_api_key_rotation_issues_unresolved",
        table_name="df_engine_api_key_rotation_issues",
    )
    op.drop_table("df_engine_api_key_rotation_issues")
