"""alter df engine menus created by nullable

Revision ID: e344a4281db5
Revises: 7a1c9e2b4f0d
Create Date: 2026-08-26 14:04:56.275961

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.mysql import BIGINT


# revision identifiers, used by Alembic.
revision: str = "e344a4281db5"
down_revision: Union[str, Sequence[str], None] = "7a1c9e2b4f0d"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.alter_column("df_engine_menus", "created_by", existing_type=BIGINT(unsigned=True), nullable=True)


def downgrade() -> None:
    """Downgrade schema."""
    op.execute(
        "DELETE FROM df_engine_menu_feature_mappings "
        "WHERE menu_id IN (SELECT id FROM df_engine_menus WHERE created_by IS NULL)"
    )
    op.execute("DELETE FROM df_engine_menus WHERE created_by IS NULL")
    op.alter_column("df_engine_menus", "created_by", existing_type=BIGINT(unsigned=True), nullable=False)
