"""rename df engine api snapshots to df engine api key snapshots

Revision ID: 3957a09d40aa
Revises: f1a2b3c4d5e6
Create Date: 2026-09-05 13:36:55.863149

"""

from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = "3957a09d40aa"
down_revision: Union[str, Sequence[str], None] = "0b12762ad8b5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.rename_table("df_engine_api_snapshots", "df_engine_api_key_snapshots")


def downgrade() -> None:
    """Downgrade schema."""
    op.rename_table("df_engine_api_key_snapshots", "df_engine_api_snapshots")
