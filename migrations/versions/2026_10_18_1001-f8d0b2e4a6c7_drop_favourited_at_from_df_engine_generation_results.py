"""drop_favourited_at_from_df_engine_generation_results

Revision ID: f8d0b2e4a6c7
Revises: e7c9a1d3f5b6
Create Date: 2026-10-18 10:01:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "f8d0b2e4a6c7"
down_revision: Union[str, Sequence[str], None] = "e7c9a1d3f5b6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

RESULTS = "df_engine_generation_results"
FAVOURITES = "df_engine_generation_favourites"


def upgrade() -> None:
    # existing favourites were owner/override-only, so the favouriter is whoever last touched the row
    op.execute(
        f"INSERT INTO {FAVOURITES} (favourited_at, user_id, result_id) "
        f"SELECT favourited_at, COALESCE(updated_by, created_by), id FROM {RESULTS} "
        f"WHERE favourited_at IS NOT NULL AND COALESCE(updated_by, created_by) IS NOT NULL"
    )
    op.drop_column(RESULTS, "favourited_at")


def downgrade() -> None:
    op.add_column(RESULTS, sa.Column("favourited_at", sa.DateTime(), nullable=True))
    op.execute(
        f"UPDATE {RESULTS} r JOIN (SELECT result_id, MIN(favourited_at) AS favourited_at FROM {FAVOURITES} "
        f"GROUP BY result_id) f ON f.result_id = r.id SET r.favourited_at = f.favourited_at"
    )
