"""create df_engine_keyframe_details

Revision ID: d6f7b8c9e0a1
Revises: c5e6a7b8d9f0
Create Date: 2026-09-10 14:20:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.mysql import BIGINT


# revision identifiers, used by Alembic.
revision: str = "d6f7b8c9e0a1"
down_revision: Union[str, Sequence[str], None] = "c5e6a7b8d9f0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TABLE_NAME = "df_engine_keyframe_details"
SHOT_SIZES = sa.Enum(
    "extreme_wide",
    "medium_wide",
    "wide",
    "medium",
    "medium_close_up",
    "close_up",
    "extreme_close_up",
    "insert",
    name="shot_sizes",
)
ANGELS = sa.Enum(
    "eye_level",
    "low",
    "high",
    "ground_level",
    "knee_level",
    "hip_level",
    "over_the_shoulder",
    "overhead",
    "top_view",
    "aerial",
    "dutch",
    "pov",
    name="angels",
)
FOCAL_LENGTHS = sa.Enum("mm_14", "mm_24", "mm_35", "mm_50", "mm_85", "mm_135", name="focal_lengths")


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        TABLE_NAME,
        sa.Column("id", BIGINT(unsigned=True), primary_key=True, autoincrement=True),
        sa.Column("generation_id", BIGINT(unsigned=True), sa.ForeignKey("df_engine_generations.id"), nullable=False),
        sa.Column("updated_at", sa.DateTime, nullable=True),
        sa.Column("archieved_at", sa.DateTime, nullable=True),
        sa.Column("shot_id", BIGINT(unsigned=True), sa.ForeignKey("df_engine_scene_shots.id"), nullable=False),
        sa.Column("shot_size", SHOT_SIZES, nullable=True, server_default="extreme_wide"),
        sa.Column("angel", ANGELS, nullable=True, server_default="low"),
        sa.Column("focal", FOCAL_LENGTHS, nullable=True, server_default="mm_50"),
        sa.Column("parameter", sa.JSON, nullable=True),
    )
    op.create_index("idx_keyframe_details_shot_id", TABLE_NAME, ["shot_id"])


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table(TABLE_NAME)
    SHOT_SIZES.drop(op.get_bind(), checkfirst=True)
    ANGELS.drop(op.get_bind(), checkfirst=True)
    FOCAL_LENGTHS.drop(op.get_bind(), checkfirst=True)
