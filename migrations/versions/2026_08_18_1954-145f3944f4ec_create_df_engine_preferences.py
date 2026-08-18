"""create df engine preferences

Revision ID: 145f3944f4ec
Revises: 2a9c5200f1ac
Create Date: 2026-08-18 19:54:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.mysql import BIGINT, DECIMAL


# revision identifiers, used by Alembic.
revision: str = "145f3944f4ec"
down_revision: Union[str, Sequence[str], None] = "2a9c5200f1ac"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "df_engine_preferences",
        sa.Column("id", BIGINT(unsigned=True), primary_key=True, autoincrement=True),
        sa.Column("created_at", sa.DateTime, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime, nullable=True),
        sa.Column(
            "user_id",
            BIGINT(unsigned=True),
            sa.ForeignKey("users.id"),
            nullable=False,
            unique=True,
        ),
        sa.Column("theme", sa.String(20), nullable=False, server_default="dark"),
        sa.Column("accent", sa.String(20), nullable=False, server_default="teal"),
        sa.Column("language", sa.String(20), nullable=False, server_default="english"),
        sa.Column("default_aspect_ratio", sa.String(20), nullable=False, server_default="16:9"),
        sa.Column("default_size", sa.String(20), nullable=False, server_default="4K"),
        sa.Column("confirm_before_spending", DECIMAL(10, 2), nullable=False, server_default="0.50"),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table("df_engine_preferences")
