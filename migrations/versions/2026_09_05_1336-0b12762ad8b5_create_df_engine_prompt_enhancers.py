"""create df engine prompt enhancers

Revision ID: 0b12762ad8b5
Revises: f1a2b3c4d5e6
Create Date: 2026-09-05 13:36:56.614769

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.mysql import BIGINT


# revision identifiers, used by Alembic.
revision: str = "0b12762ad8b5"
down_revision: Union[str, Sequence[str], None] = "f1a2b3c4d5e6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "df_engine_prompt_enhancers",
        sa.Column("id", BIGINT(unsigned=True), primary_key=True, autoincrement=True),
        sa.Column("created_at", sa.DateTime, server_default=sa.func.now()),
        sa.Column("model_id", BIGINT(unsigned=True), sa.ForeignKey("df_engine_model_options.id"), nullable=False),
        sa.Column(
            "featureable_id",
            BIGINT(unsigned=True),
            nullable=False,
            comment="Polymorphic id, paired with featureable_type",
        ),
        sa.Column(
            "featureable_type",
            sa.String(255),
            nullable=False,
            comment="Polymorphic discriminator: df_engine_features or df_engine_feature_snapshots",
        ),
        sa.Column(
            "sourceable_id",
            BIGINT(unsigned=True),
            nullable=False,
            comment="Polymorphic id, paired with sourceable_type",
        ),
        sa.Column(
            "sourceable_type",
            sa.String(255),
            nullable=False,
            comment="Polymorphic discriminator: df_engine_api_keys or df_engine_api_key_snapshots",
        ),
        sa.Column("project_id", BIGINT(unsigned=True), sa.ForeignKey("projects.id"), nullable=True),
        sa.Column("task_id", BIGINT(unsigned=True), sa.ForeignKey("project_tasks.id"), nullable=True),
        sa.Column("raw", sa.Text, nullable=True),
        sa.Column("enhanced", sa.Text, nullable=True),
        sa.Column("is_processing", sa.Boolean, nullable=False, server_default=sa.true()),
        sa.Column("response", sa.JSON, nullable=True),
        sa.Column("status_code", sa.Integer, nullable=True),
        sa.Column("token_usage", sa.Integer, nullable=False, server_default="0"),
        sa.Column("cost", sa.DECIMAL(10, 2), nullable=False, server_default="0.00"),
        sa.Column("created_by", BIGINT(unsigned=True), sa.ForeignKey("users.id"), nullable=True),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table("df_engine_prompt_enhancers")
