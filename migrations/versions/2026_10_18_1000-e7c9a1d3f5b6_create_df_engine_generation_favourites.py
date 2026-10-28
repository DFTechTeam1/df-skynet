"""create_df_engine_generation_favourites

Revision ID: e7c9a1d3f5b6
Revises: d6b8f0c2e4a5
Create Date: 2026-10-18 10:00:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.mysql import BIGINT

# revision identifiers, used by Alembic.
revision: str = "e7c9a1d3f5b6"
down_revision: Union[str, Sequence[str], None] = "d6b8f0c2e4a5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TABLE_NAME = "df_engine_generation_favourites"


def upgrade() -> None:
    op.create_table(
        TABLE_NAME,
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("favourited_at", sa.DateTime(), nullable=False),
        sa.Column("user_id", BIGINT(unsigned=True), sa.ForeignKey("users.id"), nullable=False),
        sa.Column(
            "result_id",
            BIGINT(unsigned=True),
            sa.ForeignKey("df_engine_generation_results.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.UniqueConstraint("user_id", "result_id", name="uq_generation_favourites_user_result"),
    )


def downgrade() -> None:
    op.drop_table(TABLE_NAME)
