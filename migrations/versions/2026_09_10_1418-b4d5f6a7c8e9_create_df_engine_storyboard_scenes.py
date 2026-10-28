"""create df_engine_storyboard_scenes

Revision ID: b4d5f6a7c8e9
Revises: a3c4e5f6b7d8
Create Date: 2026-09-10 14:18:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.mysql import BIGINT


# revision identifiers, used by Alembic.
revision: str = "b4d5f6a7c8e9"
down_revision: Union[str, Sequence[str], None] = "a3c4e5f6b7d8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TABLE_NAME = "df_engine_storyboard_scenes"


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        TABLE_NAME,
        sa.Column("id", BIGINT(unsigned=True), primary_key=True, autoincrement=True),
        sa.Column("created_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime, nullable=True),
        sa.Column("story_id", BIGINT(unsigned=True), sa.ForeignKey("df_engine_generations.id"), nullable=False),
    )
    op.create_index("idx_storyboard_scenes_story_created_at", TABLE_NAME, ["story_id", "created_at"])


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table(TABLE_NAME)
