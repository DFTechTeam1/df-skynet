"""create df_engine_motion_details

Revision ID: e7a8c9d0f1b2
Revises: d6f7b8c9e0a1
Create Date: 2026-09-10 14:21:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.mysql import BIGINT


# revision identifiers, used by Alembic.
revision: str = "e7a8c9d0f1b2"
down_revision: Union[str, Sequence[str], None] = "d6f7b8c9e0a1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TABLE_NAME = "df_engine_motion_details"
MOTIONS = sa.Enum(
    "static",
    "pan",
    "tilt",
    "push_in",
    "pull_back",
    "track",
    "crane",
    "handheld",
    name="motions",
)


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        TABLE_NAME,
        sa.Column("id", BIGINT(unsigned=True), primary_key=True, autoincrement=True),
        sa.Column("generation_id", BIGINT(unsigned=True), sa.ForeignKey("df_engine_generations.id"), nullable=False),
        sa.Column("updated_at", sa.DateTime, nullable=True),
        sa.Column("archieved_at", sa.DateTime, nullable=True),
        sa.Column("shot_id", BIGINT(unsigned=True), sa.ForeignKey("df_engine_scene_shots.id"), nullable=False),
        sa.Column("motion", MOTIONS, nullable=True, server_default="static"),
        sa.Column("parameter", sa.JSON, nullable=True),
    )
    op.create_index("idx_motion_details_shot_id", TABLE_NAME, ["shot_id"])


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table(TABLE_NAME)
    MOTIONS.drop(op.get_bind(), checkfirst=True)
