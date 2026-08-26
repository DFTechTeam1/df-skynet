"""alter df engine setting logs created by nullable

Revision ID: c8ade8d3fb39
Revises: 79fe1cdd9afe
Create Date: 2026-08-26 14:05:01.564508

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.mysql import BIGINT


# revision identifiers, used by Alembic.
revision: str = "c8ade8d3fb39"
down_revision: Union[str, Sequence[str], None] = "79fe1cdd9afe"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.alter_column("df_engine_setting_logs", "created_by", existing_type=BIGINT(unsigned=True), nullable=True)


def downgrade() -> None:
    """Downgrade schema."""
    op.execute("DELETE FROM df_engine_setting_logs WHERE created_by IS NULL")
    op.alter_column("df_engine_setting_logs", "created_by", existing_type=BIGINT(unsigned=True), nullable=False)
