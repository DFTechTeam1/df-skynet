"""create df_engine_guardrail_validations

Revision ID: 3a1b2c3d4e57
Revises: 3a1b2c3d4e56
Create Date: 2026-11-18 10:06:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.mysql import BIGINT

# revision identifiers, used by Alembic.
revision: str = "3a1b2c3d4e57"
down_revision: Union[str, Sequence[str], None] = "3a1b2c3d4e56"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


TABLE_NAME = "df_engine_guardrail_validations"


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        TABLE_NAME,
        sa.Column("id", BIGINT(unsigned=True), primary_key=True, autoincrement=True),
        sa.Column("uid", sa.CHAR(36), nullable=False, unique=True),
        sa.Column("created_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
        sa.Column("menu_id", BIGINT(unsigned=True), sa.ForeignKey("df_engine_menus.id"), nullable=False),
        sa.Column("feature_id", BIGINT(unsigned=True), sa.ForeignKey("df_engine_features.id"), nullable=False),
        sa.Column("payload", sa.JSON, nullable=False),
        sa.Column("response", sa.JSON, nullable=False),
        sa.Column("status_code", sa.Integer, nullable=False, server_default="200"),
        sa.Column("total_tokens", BIGINT(unsigned=True), nullable=False, server_default="0"),
        sa.Column("cached_tokens", BIGINT(unsigned=True), nullable=False, server_default="0"),
        sa.Column("cost", sa.DECIMAL(10, 2), nullable=False, server_default="0"),
        sa.Column("exchange_rate", sa.DECIMAL(20, 8), nullable=False, server_default="0"),
        sa.Column("created_by", BIGINT(unsigned=True), sa.ForeignKey("users.id"), nullable=False),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table(TABLE_NAME)
