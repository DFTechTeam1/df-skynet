"""create df_engine_scene_shots

Revision ID: c5e6a7b8d9f0
Revises: b4d5f6a7c8e9
Create Date: 2026-09-10 14:19:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.mysql import BIGINT


# revision identifiers, used by Alembic.
revision: str = "c5e6a7b8d9f0"
down_revision: Union[str, Sequence[str], None] = "b4d5f6a7c8e9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TABLE_NAME = "df_engine_scene_shots"
INTERIOR_STYLES = sa.Enum("interior", "exterior", "interior_exterior", name="interior_styles")
TIME_OF_DAYS = sa.Enum(
    "pre_dawn",
    "sunrise",
    "morning",
    "midday",
    "afternoon",
    "golden_hour",
    "dusk",
    "blue_hour",
    "night",
    name="time_of_days",
)
LIGHTING_MOODS = sa.Enum(
    "natural",
    "soft_diffused",
    "hard_high_contrast",
    "warm_practical",
    "moody_low_key",
    "high_key_bright",
    "silhouette_backlit",
    "neon",
    "overcast_flat",
    name="lighting_moods",
)


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        TABLE_NAME,
        sa.Column("id", BIGINT(unsigned=True), primary_key=True, autoincrement=True),
        sa.Column("created_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime, nullable=True),
        sa.Column("archieved_at", sa.DateTime, nullable=True),
        sa.Column("scene_id", BIGINT(unsigned=True), sa.ForeignKey("df_engine_storyboard_scenes.id"), nullable=False),
        sa.Column("name", sa.String(255), nullable=True),
        sa.Column("interior_style", INTERIOR_STYLES, nullable=True, server_default="interior"),
        sa.Column("time_of_day", TIME_OF_DAYS, nullable=True, server_default="sunrise"),
        sa.Column("lighting_mood", LIGHTING_MOODS, nullable=True, server_default="natural"),
    )
    op.create_index("idx_scene_shots_scene_id", TABLE_NAME, ["scene_id"])


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table(TABLE_NAME)
    INTERIOR_STYLES.drop(op.get_bind(), checkfirst=True)
    TIME_OF_DAYS.drop(op.get_bind(), checkfirst=True)
    LIGHTING_MOODS.drop(op.get_bind(), checkfirst=True)
