"""add_song_id_to_df_engine_generations

Revision ID: 972852427abe
Revises: c6a1e4b9d2f8
Create Date: 2026-10-03 19:14:02.266122

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.mysql import BIGINT


# revision identifiers, used by Alembic.
revision: str = "972852427abe"
down_revision: Union[str, Sequence[str], None] = "c6a1e4b9d2f8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TABLE_NAME = "df_engine_generations"


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        TABLE_NAME,
        sa.Column("song_id", BIGINT(unsigned=True), sa.ForeignKey("project_song_lists.id"), nullable=True),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column(TABLE_NAME, "song_id")
