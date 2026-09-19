"""add image_edit to generation_kinds

Revision ID: d8f2a4c6e1b3
Revises: b7e4d2f9a1c6
Create Date: 2026-09-19 10:00:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "d8f2a4c6e1b3"
down_revision: Union[str, Sequence[str], None] = "b7e4d2f9a1c6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TABLE_NAME = "df_engine_generations"

OLD_KINDS = ("image", "video", "element", "storyboard", "keyframe", "motion", "chat", "enhancer")
NEW_KINDS = OLD_KINDS + ("image_edit",)


def upgrade() -> None:
    """Upgrade schema."""
    op.alter_column(
        TABLE_NAME,
        "kind",
        existing_type=sa.Enum(*OLD_KINDS, name="generation_kinds"),
        type_=sa.Enum(*NEW_KINDS, name="generation_kinds"),
        existing_nullable=False,
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.alter_column(
        TABLE_NAME,
        "kind",
        existing_type=sa.Enum(*NEW_KINDS, name="generation_kinds"),
        type_=sa.Enum(*OLD_KINDS, name="generation_kinds"),
        existing_nullable=False,
    )
