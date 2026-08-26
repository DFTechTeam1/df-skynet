"""alter df engine features created by nullable

Revision ID: 5bf8a419c4fd
Revises: e344a4281db5
Create Date: 2026-08-26 14:04:57.322039

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.mysql import BIGINT


# revision identifiers, used by Alembic.
revision: str = "5bf8a419c4fd"
down_revision: Union[str, Sequence[str], None] = "e344a4281db5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.alter_column("df_engine_features", "created_by", existing_type=BIGINT(unsigned=True), nullable=True)


def downgrade() -> None:
    """Downgrade schema."""
    op.execute(
        "DELETE FROM df_engine_menu_feature_mappings "
        "WHERE feature_id IN (SELECT id FROM df_engine_features WHERE created_by IS NULL)"
    )
    op.execute("DELETE FROM df_engine_features WHERE created_by IS NULL")
    op.alter_column("df_engine_features", "created_by", existing_type=BIGINT(unsigned=True), nullable=False)
