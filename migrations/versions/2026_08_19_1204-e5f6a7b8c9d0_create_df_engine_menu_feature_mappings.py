"""create df engine menu feature mappings

Revision ID: e5f6a7b8c9d0
Revises: d4e5f6a7b8c9
Create Date: 2026-08-19 12:04:00.000000

Renamed from the legacy df_engine_feature_mappings table (page_id ->
menu_id, action_id -> feature_id). Part of the squashed baseline (see
a1b2c3d4e5f6).
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.mysql import BIGINT


# revision identifiers, used by Alembic.
revision: str = "e5f6a7b8c9d0"
down_revision: Union[str, Sequence[str], None] = "d4e5f6a7b8c9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "df_engine_menu_feature_mappings",
        sa.Column("id", BIGINT(unsigned=True), primary_key=True, autoincrement=True),
        sa.Column("created_at", sa.DateTime, server_default=sa.func.now()),
        sa.Column("uid", sa.CHAR(36), nullable=False, unique=True),
        sa.Column(
            "feature_id",
            BIGINT(unsigned=True),
            sa.ForeignKey("df_engine_features.id"),
            nullable=False,
        ),
        sa.Column(
            "menu_id",
            BIGINT(unsigned=True),
            sa.ForeignKey("df_engine_menus.id"),
            nullable=False,
        ),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table("df_engine_menu_feature_mappings")
