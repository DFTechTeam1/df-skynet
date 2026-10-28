"""widen df_engine_generations.response to longtext

- base64-encoded image responses routinely exceed TEXT's 64KB cap; LONGTEXT
  (4GB) covers any realistic image/video payload size

Revision ID: b8e1c3f6a2d9
Revises: a3d9f6e2c8b4
Create Date: 2026-09-19 15:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "b8e1c3f6a2d9"
down_revision: Union[str, Sequence[str], None] = "a3d9f6e2c8b4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TABLE_NAME = "df_engine_generations"


def upgrade() -> None:
    """Upgrade schema."""
    op.alter_column(
        TABLE_NAME, "response", existing_type=sa.Text(), type_=sa.Text(length=4294967295), existing_nullable=True
    )


def downgrade() -> None:
    """Downgrade schema."""
    # ponytail: narrowing back to TEXT (64KB) is lossy once any row holds a
    # base64 image/video payload past that cap (the reason this migration
    # exists) — MySQL errors with "Data too long" instead of truncating
    # silently, so we leave the column widened rather than risk data loss.
    pass
