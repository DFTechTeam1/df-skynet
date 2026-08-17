"""create df engine prompt templates

Revision ID: 810f1b851db3
Revises: cf4a69dbb241
Create Date: 2026-08-16 22:25:13.860235

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.mysql import BIGINT


# revision identifiers, used by Alembic.
revision: str = "810f1b851db3"
down_revision: Union[str, Sequence[str], None] = "cf4a69dbb241"
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

    # Deferred FK: df_engine_action_mappings.template_id was created (previous migration)
    # before this table existed, so the constraint is added now instead.
    op.create_foreign_key(
        "fk_df_engine_action_mappings_template_id",
        "df_engine_action_mappings",
        "df_engine_prompt_templates",
        ["template_id"],
        ["id"],
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_constraint(
        "fk_df_engine_action_mappings_template_id",
        "df_engine_action_mappings",
        type_="foreignkey",
    )
    op.drop_table("df_engine_prompt_templates")
