"""add thumbnail to df_engine_upload_files

Filename of the video thumbnail stored locally in `storages/thumbnail`; null for everything else.

Revision ID: 3a1b2c3d4e75
Revises: 3a1b2c3d4e74
Create Date: 2026-11-27 10:01:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "3a1b2c3d4e75"
down_revision: Union[str, Sequence[str], None] = "3a1b2c3d4e74"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


TABLE_NAME = "df_engine_upload_files"


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(TABLE_NAME, sa.Column("thumbnail", sa.String(255), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column(TABLE_NAME, "thumbnail")
