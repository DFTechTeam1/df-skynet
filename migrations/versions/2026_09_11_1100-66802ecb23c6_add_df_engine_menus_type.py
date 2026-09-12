"""add df_engine_menus.type

Menus are now mapped to df_engine_settings (key=menu_management_options)
option values via this new unique, required `type` column. Dev-only table,
so existing rows (and their feature mappings) are wiped rather than backfilled.

Revision ID: 66802ecb23c6
Revises: 17e8cc4fb42d
Create Date: 2026-09-11 11:00:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "66802ecb23c6"
down_revision: Union[str, Sequence[str], None] = "17e8cc4fb42d"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.execute("DELETE FROM df_engine_menu_feature_mappings")
    op.execute("DELETE FROM df_engine_menus")
    op.add_column("df_engine_menus", sa.Column("type", sa.String(255), nullable=False))
    op.create_unique_constraint("uq_df_engine_menus_type", "df_engine_menus", ["type"])


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_constraint("uq_df_engine_menus_type", "df_engine_menus", type_="unique")
    op.drop_column("df_engine_menus", "type")
