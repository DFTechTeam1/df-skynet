"""add unique project_id to df_engine_project_settings

One override per project; `POST /setting/{uid}` upserts on this key. Fails if a project already has
more than one row: nothing is deleted here, decide which row to keep first.

Revision ID: 3a1b2c3d4e73
Revises: 3a1b2c3d4e72
Create Date: 2026-11-26 12:00:00.000000

"""

from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "3a1b2c3d4e73"
down_revision: Union[str, Sequence[str], None] = "3a1b2c3d4e72"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


TABLE_NAME = "df_engine_project_settings"
CONSTRAINT = "uq_df_engine_project_settings_project_id"
FK_INDEX = "idx_df_engine_project_settings_project_id"


def upgrade() -> None:
    """Upgrade schema."""
    op.create_unique_constraint(CONSTRAINT, TABLE_NAME, ["project_id"])


def downgrade() -> None:
    """Downgrade schema."""
    # MySQL won't drop the only index backing the project_id foreign key, so add a plain one first
    op.create_index(FK_INDEX, TABLE_NAME, ["project_id"])
    op.drop_constraint(CONSTRAINT, TABLE_NAME, type_="unique")
