"""add folder to df_engine_upload_files.type

- widen the type enum so a folder can have its own row (created empty,
  with no file inside it), instead of only ever representing video/image files

Revision ID: c1d2e3f4a5b6
Revises: b5da41b87763
Create Date: 2026-09-12 16:00:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "c1d2e3f4a5b6"
down_revision: Union[str, Sequence[str], None] = "b5da41b87763"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TABLE = "df_engine_upload_files"
OLD_ENUM = sa.Enum("video", "image", name="upload_file_types")
NEW_ENUM = sa.Enum("video", "image", "folder", name="upload_file_types")


def upgrade() -> None:
    """Upgrade schema."""
    op.alter_column(TABLE, "type", existing_type=OLD_ENUM, type_=NEW_ENUM, existing_nullable=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.alter_column(TABLE, "type", existing_type=NEW_ENUM, type_=OLD_ENUM, existing_nullable=False)
