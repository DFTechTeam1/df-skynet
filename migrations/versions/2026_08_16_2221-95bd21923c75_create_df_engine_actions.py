"""create df engine actions

Revision ID: 95bd21923c75
Revises: cabc7829b44b
Create Date: 2026-08-16 22:21:52.653048

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.mysql import BIGINT


# revision identifiers, used by Alembic.
revision: str = "95bd21923c75"
down_revision: Union[str, Sequence[str], None] = "cabc7829b44b"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "df_engine_actions",
        sa.Column("id", BIGINT(unsigned=True), primary_key=True, autoincrement=True),
        sa.Column("created_at", sa.DateTime, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime, nullable=True),
        sa.Column("uid", sa.CHAR(36), nullable=False, unique=True),
        sa.Column(
            "page_id",
            BIGINT(unsigned=True),
            sa.ForeignKey("df_engine_pages.id"),
            nullable=False,
        ),
        sa.Column("name", sa.String(255), nullable=False, unique=True),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default=sa.true()),
        sa.Column(
            "created_by",
            BIGINT(unsigned=True),
            sa.ForeignKey("users.id"),
            nullable=False,
        ),
        sa.Column(
            "updated_by",
            BIGINT(unsigned=True),
            sa.ForeignKey("users.id"),
            nullable=True,
        ),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table("df_engine_actions")
