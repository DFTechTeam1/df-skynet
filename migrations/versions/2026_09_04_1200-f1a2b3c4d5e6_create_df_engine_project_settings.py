"""create df engine project settings

Revision ID: f1a2b3c4d5e6
Revises: a3d7f1c9b204
Create Date: 2026-09-04 12:00:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.mysql import BIGINT


# revision identifiers, used by Alembic.
revision: str = "f1a2b3c4d5e6"
down_revision: Union[str, Sequence[str], None] = "a3d7f1c9b204"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "df_engine_project_settings",
        sa.Column("id", BIGINT(unsigned=True), primary_key=True, autoincrement=True),
        sa.Column("created_at", sa.DateTime, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime, nullable=True),
        sa.Column("project_id", BIGINT(unsigned=True), sa.ForeignKey("projects.id"), nullable=False),
        sa.Column("token_usage_limit", sa.Integer, nullable=False),
        sa.Column("concurent_generations", sa.Integer, nullable=False),
        sa.Column("compose_input_max_chars", sa.Integer, nullable=False),
        sa.Column("storyboard_prompt_chars", sa.Integer, nullable=False),
        sa.Column("max_scene_per_storyboard", sa.Integer, nullable=False),
        sa.Column("max_shot_per_scene", sa.Integer, nullable=False),
        sa.Column("created_by", BIGINT(unsigned=True), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("updated_by", BIGINT(unsigned=True), sa.ForeignKey("users.id"), nullable=True),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table("df_engine_project_settings")
