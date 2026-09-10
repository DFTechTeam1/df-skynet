"""create df engine generations

Revision ID: c5e7a1b3d9f2
Revises: f1a2b3c4d5e6
Create Date: 2026-09-10 12:00:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.mysql import BIGINT


# revision identifiers, used by Alembic.
revision: str = "c5e7a1b3d9f2"
down_revision: Union[str, Sequence[str], None] = "f1a2b3c4d5e6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TABLE_NAME = "df_engine_generations"

GENERATION_KINDS = sa.Enum(
    "image",
    "video",
    "element",
    "storyboard",
    "keyframe",
    "motion",
    "chat",
    "enhancer",
    name="generation_kinds",
)
GENERATION_STATUSES = sa.Enum(
    "queued",
    "processing",
    "success",
    "failed",
    name="generation_statuses",
)


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        TABLE_NAME,
        sa.Column("id", BIGINT(unsigned=True), primary_key=True, autoincrement=True),
        sa.Column("created_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
        sa.Column("kind", GENERATION_KINDS, nullable=False),
        sa.Column("model_id", BIGINT(unsigned=True), sa.ForeignKey("df_engine_model_options.id"), nullable=False),
        sa.Column("menu_id", BIGINT(unsigned=True), sa.ForeignKey("df_engine_menus.id"), nullable=False),
        sa.Column("feature_id", BIGINT(unsigned=True), sa.ForeignKey("df_engine_features.id"), nullable=False),
        sa.Column("sourceable_id", BIGINT(unsigned=True), nullable=False),
        sa.Column("sourceable_type", sa.String(255), nullable=False),
        sa.Column("project_id", BIGINT(unsigned=True), sa.ForeignKey("projects.id"), nullable=True),
        sa.Column("task_id", BIGINT(unsigned=True), sa.ForeignKey("project_tasks.id"), nullable=True),
        sa.Column("prompt", sa.Text, nullable=False),
        sa.Column("status", GENERATION_STATUSES, nullable=False, server_default="processing"),
        sa.Column("response", sa.JSON, nullable=True),
        sa.Column("status_code", sa.Integer, nullable=True),
        sa.Column("token_usage", sa.Integer, nullable=True),
        sa.Column("cost", sa.DECIMAL(10, 2), nullable=True),
        sa.Column("created_by", BIGINT(unsigned=True), sa.ForeignKey("users.id"), nullable=True),
    )
    op.create_index("idx_generations_kind", TABLE_NAME, ["kind"])
    op.create_index("idx_generations_kind_created_by", TABLE_NAME, ["kind", "created_by"])
    op.create_index("idx_generations_project_task", TABLE_NAME, ["project_id", "task_id"])
    op.create_index("idx_generations_created_by", TABLE_NAME, ["created_by"])
    op.create_index("idx_generations_status_created_at", TABLE_NAME, ["status", "created_at"])
    op.create_index("idx_generations_sourceable", TABLE_NAME, ["sourceable_id", "sourceable_type"])


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table(TABLE_NAME)
    GENERATION_KINDS.drop(op.get_bind(), checkfirst=True)
    GENERATION_STATUSES.drop(op.get_bind(), checkfirst=True)
