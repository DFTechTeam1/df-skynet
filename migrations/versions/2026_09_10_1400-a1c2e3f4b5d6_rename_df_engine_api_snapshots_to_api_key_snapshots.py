"""rename df_engine_api_snapshots to df_engine_api_key_snapshots

Revision ID: a1c2e3f4b5d6
Revises: d7b3f9a2c1e4
Create Date: 2026-09-10 14:00:00.000000

"""

from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = "a1c2e3f4b5d6"
down_revision: Union[str, Sequence[str], None] = "d8c4a0e6b2f5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

OLD_NAME = "df_engine_api_snapshots"
NEW_NAME = "df_engine_api_key_snapshots"


def upgrade() -> None:
    """Upgrade schema."""
    op.rename_table(OLD_NAME, NEW_NAME)


def downgrade() -> None:
    """Downgrade schema."""
    op.rename_table(NEW_NAME, OLD_NAME)
