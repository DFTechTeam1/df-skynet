"""add df_engine_generations.uid

Backfills existing rows with a generated uuid4 before enforcing uniqueness,
matching df_engine_generation_results.uid.

Revision ID: e9d8c7b6a5f4
Revises: c9bcfd01292e
Create Date: 2026-09-16 10:00:00.000000

"""

from typing import Sequence, Union
from uuid import uuid4

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "e9d8c7b6a5f4"
down_revision: Union[str, Sequence[str], None] = "c9bcfd01292e"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TABLE_NAME = "df_engine_generations"


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(TABLE_NAME, sa.Column("uid", sa.CHAR(36), nullable=True))

    generations = sa.table("df_engine_generations", sa.column("id", sa.BigInteger), sa.column("uid", sa.CHAR(36)))
    conn = op.get_bind()
    for (row_id,) in conn.execute(sa.select(generations.c.id)):
        conn.execute(generations.update().where(generations.c.id == row_id).values(uid=str(uuid4())))

    op.alter_column(TABLE_NAME, "uid", existing_type=sa.CHAR(36), nullable=False)
    op.create_unique_constraint("uq_df_engine_generations_uid", TABLE_NAME, ["uid"])


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_constraint("uq_df_engine_generations_uid", TABLE_NAME, type_="unique")
    op.drop_column(TABLE_NAME, "uid")
