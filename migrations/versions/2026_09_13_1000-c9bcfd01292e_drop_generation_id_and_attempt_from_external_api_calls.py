"""drop generation_id and attempt from df_engine_external_api_calls

- this table is a pure logging table for outbound API calls (openrouter, udin, ...)
  and should carry no relation onto df_engine_generations

Revision ID: c9bcfd01292e
Revises: c1d2e3f4a5b6
Create Date: 2026-09-13 10:00:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.mysql import BIGINT

# revision identifiers, used by Alembic.
revision: str = "c9bcfd01292e"
down_revision: Union[str, Sequence[str], None] = "c1d2e3f4a5b6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TABLE = "df_engine_external_api_calls"
FK_NAME = "fk_df_engine_openrouter_logs_generation_id"
INDEX_NAME = "idx_external_api_calls_generation_attempt"


def upgrade() -> None:
    """Upgrade schema."""
    op.drop_constraint(FK_NAME, TABLE, type_="foreignkey")
    op.drop_index(INDEX_NAME, table_name=TABLE)
    op.drop_column(TABLE, "attempt")
    op.drop_column(TABLE, "generation_id")


def downgrade() -> None:
    """Downgrade schema."""
    op.add_column(TABLE, sa.Column("generation_id", BIGINT(unsigned=True), nullable=True))
    op.add_column(TABLE, sa.Column("attempt", sa.Integer(), nullable=True))
    op.create_index(INDEX_NAME, TABLE, ["generation_id", "attempt"])
    op.create_foreign_key(FK_NAME, TABLE, "df_engine_generations", ["generation_id"], ["id"])
