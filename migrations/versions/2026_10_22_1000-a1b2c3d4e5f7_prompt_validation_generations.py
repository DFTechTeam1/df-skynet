"""allow prompt_validation generations: nullable menu_id/feature_id, new kind

Revision ID: a1b2c3d4e5f7
Revises: f8d0b2e4a6c7
Create Date: 2026-10-22 10:00:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.mysql import BIGINT

# revision identifiers, used by Alembic.
revision: str = "a1b2c3d4e5f7"
down_revision: Union[str, Sequence[str], None] = "f8d0b2e4a6c7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TABLE_NAME = "df_engine_generations"

OLD_KINDS = ("image", "video", "element", "storyboard", "keyframe", "motion", "chat", "enhancer", "image_edit")
NEW_KINDS = OLD_KINDS + ("prompt_validation",)


def upgrade() -> None:
    """Upgrade schema."""
    for column in ("menu_id", "feature_id"):
        op.alter_column(TABLE_NAME, column, existing_type=BIGINT(unsigned=True), nullable=True, server_default=None)
    op.alter_column(
        TABLE_NAME,
        "kind",
        existing_type=sa.Enum(*OLD_KINDS, name="generation_kinds"),
        type_=sa.Enum(*NEW_KINDS, name="generation_kinds"),
        existing_nullable=False,
    )


def downgrade() -> None:
    """Downgrade schema. `prompt_validation` rows have no menu/feature, so they are deleted first."""
    op.execute(f"DELETE FROM {TABLE_NAME} WHERE kind = 'prompt_validation'")
    op.alter_column(
        TABLE_NAME,
        "kind",
        existing_type=sa.Enum(*NEW_KINDS, name="generation_kinds"),
        type_=sa.Enum(*OLD_KINDS, name="generation_kinds"),
        existing_nullable=False,
    )
    for column in ("menu_id", "feature_id"):
        op.alter_column(TABLE_NAME, column, existing_type=BIGINT(unsigned=True), nullable=False)
