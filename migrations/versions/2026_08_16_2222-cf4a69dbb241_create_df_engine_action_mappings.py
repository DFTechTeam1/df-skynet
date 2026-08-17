"""create df engine action mappings

Revision ID: cf4a69dbb241
Revises: 95bd21923c75
Create Date: 2026-08-16 22:22:11.664791

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.mysql import BIGINT


# revision identifiers, used by Alembic.
revision: str = 'cf4a69dbb241'
down_revision: Union[str, Sequence[str], None] = '95bd21923c75'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # template_id -> df_engine_prompt_templates.id is added as a deferred FK in the
    # next migration (810f1b851db3), since df_engine_prompt_templates does not exist yet.
    op.create_table(
        "df_engine_action_mappings",
        sa.Column("id", BIGINT(unsigned=True), primary_key=True, autoincrement=True),
        sa.Column("created_at", sa.DateTime, server_default=sa.func.now()),
        sa.Column("uid", sa.CHAR(36), nullable=False, unique=True),
        sa.Column("action_id", BIGINT(unsigned=True), sa.ForeignKey("df_engine_actions.id"), nullable=False),
        sa.Column("template_id", BIGINT(unsigned=True), nullable=False),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table("df_engine_action_mappings")
