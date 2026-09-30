"""add enhance_id, x_min, x_max, y_min, y_max to df_engine_generations

- These absorb the columns from df_engine_image_generation_details so
  image-kind generations no longer need a separate details table.

Revision ID: a3f7c2e9b6d4
Revises: d5a2e9c1f7b3
Create Date: 2026-09-30 10:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.mysql import BIGINT

revision: str = "a3f7c2e9b6d4"
down_revision: Union[str, Sequence[str], None] = "d5a2e9c1f7b3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TABLE_NAME = "df_engine_generations"


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        TABLE_NAME,
        sa.Column("enhance_id", BIGINT(unsigned=True), sa.ForeignKey("df_engine_generations.id"), nullable=True),
    )
    op.add_column(TABLE_NAME, sa.Column("x_min", sa.DECIMAL(10, 2), nullable=True))
    op.add_column(TABLE_NAME, sa.Column("x_max", sa.DECIMAL(10, 2), nullable=True))
    op.add_column(TABLE_NAME, sa.Column("y_min", sa.DECIMAL(10, 2), nullable=True))
    op.add_column(TABLE_NAME, sa.Column("y_max", sa.DECIMAL(10, 2), nullable=True))


def downgrade() -> None:
    """Downgrade schema. MySQL DDL isn't transactional, so this tolerates a
    previously interrupted downgrade having already dropped some columns."""
    conn = op.get_bind()
    existing = {
        row[0]
        for row in conn.execute(
            sa.text(
                "SELECT COLUMN_NAME FROM information_schema.COLUMNS "
                "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = :table"
            ),
            {"table": TABLE_NAME},
        )
    }
    if "enhance_id" in existing:
        fk_name = conn.execute(
            sa.text(
                "SELECT CONSTRAINT_NAME FROM information_schema.KEY_COLUMN_USAGE "
                "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = :table "
                "AND COLUMN_NAME = 'enhance_id' AND REFERENCED_TABLE_NAME IS NOT NULL"
            ),
            {"table": TABLE_NAME},
        ).scalar()
        if fk_name:
            op.drop_constraint(fk_name, TABLE_NAME, type_="foreignkey")
    for column in ("y_max", "y_min", "x_max", "x_min", "enhance_id"):
        if column in existing:
            op.drop_column(TABLE_NAME, column)
