"""alter df engine preferences user id nullable

Revision ID: 8c12f91c237c
Revises: c8ade8d3fb39
Create Date: 2026-08-26 15:06:58.403980

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.mysql import BIGINT


# revision identifiers, used by Alembic.
revision: str = "8c12f91c237c"
down_revision: Union[str, Sequence[str], None] = "c8ade8d3fb39"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.alter_column("df_engine_preferences", "user_id", existing_type=BIGINT(unsigned=True), nullable=True)


def downgrade() -> None:
    """Downgrade schema."""
    op.execute("DELETE FROM df_engine_preferences WHERE user_id IS NULL")
    op.alter_column("df_engine_preferences", "user_id", existing_type=BIGINT(unsigned=True), nullable=False)
