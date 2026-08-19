"""create df engine prompt templates

Revision ID: c3d4e5f6a7b8
Revises: b2c3d4e5f6a7
Create Date: 2026-08-19 12:02:00.000000

Part of the squashed baseline (see a1b2c3d4e5f6). Created here, ahead of
df_engine_feature_prompt_mappings, so that migration's FK to this table can
be declared inline instead of deferred.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.mysql import BIGINT


# revision identifiers, used by Alembic.
revision: str = "c3d4e5f6a7b8"
down_revision: Union[str, Sequence[str], None] = "b2c3d4e5f6a7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "df_engine_prompt_templates",
        sa.Column("id", BIGINT(unsigned=True), primary_key=True, autoincrement=True),
        sa.Column("created_at", sa.DateTime, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime, nullable=True),
        sa.Column("uid", sa.CHAR(36), nullable=False, unique=True),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default=sa.true()),
        sa.Column("name", sa.String(255), nullable=False, unique=True),
        sa.Column("prompt", sa.Text, nullable=False),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column("created_by", BIGINT(unsigned=True), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("updated_by", BIGINT(unsigned=True), sa.ForeignKey("users.id"), nullable=True),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table("df_engine_prompt_templates")
