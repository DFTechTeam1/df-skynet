"""create df engine feature mappings

Revision ID: 2a9c5200f1ac
Revises: 810f1b851db3
Create Date: 2026-08-17 10:00:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.mysql import BIGINT


# revision identifiers, used by Alembic.
revision: str = "2a9c5200f1ac"
down_revision: Union[str, Sequence[str], None] = "810f1b851db3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "df_engine_feature_mappings",
        sa.Column("id", BIGINT(unsigned=True), primary_key=True, autoincrement=True),
        sa.Column("created_at", sa.DateTime, server_default=sa.func.now()),
        sa.Column("uid", sa.CHAR(36), nullable=False, unique=True),
        sa.Column(
            "action_id",
            BIGINT(unsigned=True),
            sa.ForeignKey("df_engine_actions.id"),
            nullable=False,
        ),
        sa.Column(
            "page_id",
            BIGINT(unsigned=True),
            sa.ForeignKey("df_engine_pages.id"),
            nullable=False,
        ),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table("df_engine_feature_mappings")
