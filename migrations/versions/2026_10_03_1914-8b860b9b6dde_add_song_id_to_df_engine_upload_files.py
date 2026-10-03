"""add_song_id_to_df_engine_upload_files

Revision ID: 8b860b9b6dde
Revises: 972852427abe
Create Date: 2026-10-03 19:14:13.470207

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.mysql import BIGINT


# revision identifiers, used by Alembic.
revision: str = "8b860b9b6dde"
down_revision: Union[str, Sequence[str], None] = "972852427abe"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TABLE_NAME = "df_engine_upload_files"


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        TABLE_NAME,
        sa.Column("song_id", BIGINT(unsigned=True), sa.ForeignKey("project_song_lists.id"), nullable=True),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column(TABLE_NAME, "song_id")
