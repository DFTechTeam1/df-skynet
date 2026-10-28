"""alter df_engine_model_options.is_main to not null, default false

Backfills any existing NULL is_main rows to false, then tightens the column
to NOT NULL DEFAULT false so every row has an explicit main/non-main state.
Compatible with the existing CHECK constraint
ck_df_engine_model_options_is_main_requires_enabled
(is_main = false OR is_enabled = true).

Revision ID: 17e8cc4fb42d
Revises: f4b6d8a0c2e3
Create Date: 2026-09-11 10:00:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "17e8cc4fb42d"
down_revision: Union[str, Sequence[str], None] = "f4b6d8a0c2e3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TABLE_NAME = "df_engine_model_options"


def upgrade() -> None:
    """Upgrade schema."""
    op.execute(f"UPDATE {TABLE_NAME} SET is_main = false WHERE is_main IS NULL")
    op.alter_column(
        TABLE_NAME,
        "is_main",
        existing_type=sa.Boolean(),
        nullable=False,
        server_default=sa.false(),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.alter_column(
        TABLE_NAME,
        "is_main",
        existing_type=sa.Boolean(),
        nullable=True,
        server_default=None,
    )
