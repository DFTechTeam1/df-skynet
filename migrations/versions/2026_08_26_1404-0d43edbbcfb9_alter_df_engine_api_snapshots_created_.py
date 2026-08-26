"""alter df engine api snapshots created by nullable

Revision ID: 0d43edbbcfb9
Revises: 3f99ef289e30
Create Date: 2026-08-26 14:04:59.457066

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.mysql import BIGINT


# revision identifiers, used by Alembic.
revision: str = "0d43edbbcfb9"
down_revision: Union[str, Sequence[str], None] = "3f99ef289e30"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.alter_column("df_engine_api_snapshots", "created_by", existing_type=BIGINT(unsigned=True), nullable=True)


def downgrade() -> None:
    """Downgrade schema."""
    op.execute("DELETE FROM df_engine_api_snapshots WHERE created_by IS NULL")
    op.alter_column("df_engine_api_snapshots", "created_by", existing_type=BIGINT(unsigned=True), nullable=False)
