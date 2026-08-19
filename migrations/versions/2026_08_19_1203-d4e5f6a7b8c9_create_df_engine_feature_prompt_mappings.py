"""create df engine feature prompt mappings

Revision ID: d4e5f6a7b8c9
Revises: c3d4e5f6a7b8
Create Date: 2026-08-19 12:03:00.000000

Renamed from the legacy df_engine_action_mappings table (action_id ->
feature_id; template_id unchanged). Unlike the original chain, no deferred
FK is needed here since df_engine_prompt_templates already exists by this
point in the squashed baseline (see a1b2c3d4e5f6).
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.mysql import BIGINT


# revision identifiers, used by Alembic.
revision: str = "d4e5f6a7b8c9"
down_revision: Union[str, Sequence[str], None] = "c3d4e5f6a7b8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "df_engine_feature_prompt_mappings",
        sa.Column("id", BIGINT(unsigned=True), primary_key=True, autoincrement=True),
        sa.Column("created_at", sa.DateTime, server_default=sa.func.now()),
        sa.Column("uid", sa.CHAR(36), nullable=False, unique=True),
        sa.Column(
            "feature_id",
            BIGINT(unsigned=True),
            sa.ForeignKey("df_engine_features.id"),
            nullable=False,
        ),
        sa.Column(
            "template_id",
            BIGINT(unsigned=True),
            sa.ForeignKey("df_engine_prompt_templates.id"),
            nullable=False,
        ),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table("df_engine_feature_prompt_mappings")
