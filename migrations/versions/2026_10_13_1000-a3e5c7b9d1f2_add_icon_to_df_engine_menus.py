"""add_icon_to_df_engine_menus

Revision ID: a3e5c7b9d1f2
Revises: 9c2d7e5a1b3f
Create Date: 2026-10-13 10:00:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "a3e5c7b9d1f2"
down_revision: Union[str, Sequence[str], None] = "9c2d7e5a1b3f"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("df_engine_menus", sa.Column("icon", sa.String(255), nullable=True, server_default=sa.text("NULL")))


def downgrade() -> None:
    op.drop_column("df_engine_menus", "icon")
