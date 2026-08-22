"""create df engine model options

Revision ID: 16d4ca9e7038
Revises: 80e2a9de2a9e
Create Date: 2026-08-22 17:19:06.434697

"""

from typing import Sequence, Union
from sqlalchemy.dialects.mysql import BIGINT
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "16d4ca9e7038"
down_revision: Union[str, Sequence[str], None] = "80e2a9de2a9e"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "df_engine_model_options",
        sa.Column("id", BIGINT(unsigned=True), primary_key=True, autoincrement=True),
        sa.Column("sync_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
        sa.Column("uid", sa.CHAR(36), nullable=False, unique=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("created", sa.BigInteger, nullable=True),
        sa.Column("model_id", sa.String(255), nullable=False),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column("architecture", sa.JSON, nullable=True),
        sa.Column(
            "type",
            sa.Enum("text", "image", "video", name="model_usage_types"),
            nullable=False,
            server_default="image",
        ),
        sa.Column("is_main", sa.Boolean, nullable=True),
        sa.Column("is_enabled", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("is_available", sa.Boolean, nullable=False, server_default=sa.true()),
        sa.Column("supported_parameters", sa.JSON, nullable=True),
        sa.Column("default_parameters", sa.JSON, nullable=True),
        sa.Column("supports_streaming", sa.Boolean, nullable=True),
        sa.Column("supported_resolutions", sa.JSON, nullable=True),
        sa.Column("supported_aspect_ratios", sa.JSON, nullable=True),
        sa.Column("supported_sizes", sa.JSON, nullable=True),
        sa.Column("supported_durations", sa.JSON, nullable=True),
        sa.Column("supported_frame_images", sa.JSON, nullable=True),
        sa.Column("generate_audio", sa.Boolean, nullable=True),
        sa.Column("allowed_passthrough_parameters", sa.JSON, nullable=True),
        sa.Column("pricing_skus", sa.JSON, nullable=True),
        sa.Column("pricing", sa.JSON, nullable=True),
        sa.Column("top_provider", sa.JSON, nullable=True),
        sa.Column("knowledge_cutoff", sa.Date, nullable=True),
        sa.Column("expiration_date", sa.Date, nullable=True),
        sa.UniqueConstraint("model_id", "type", name="uq_df_engine_model_options_model_id_type"),
        sa.CheckConstraint(
            "is_main = false OR is_enabled = true",
            name="ck_df_engine_model_options_is_main_requires_enabled",
        ),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table("df_engine_model_options")
