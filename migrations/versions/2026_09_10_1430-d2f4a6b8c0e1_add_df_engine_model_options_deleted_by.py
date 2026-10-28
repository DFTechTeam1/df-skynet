"""add df_engine_model_options.deleted_by

FK -> users.id, nullable. Set when an admin soft-deletes a model, cleared on
recover. Pairs with the existing deleted_at column.

Revision ID: d2f4a6b8c0e1
Revises: c1e2a3b4d5f6
Create Date: 2026-09-10 14:30:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.mysql import BIGINT


# revision identifiers, used by Alembic.
revision: str = "d2f4a6b8c0e1"
down_revision: Union[str, Sequence[str], None] = "c1e2a3b4d5f6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TABLE_NAME = "df_engine_model_options"
FK_NAME = "fk_df_engine_model_options_deleted_by"


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(TABLE_NAME, sa.Column("deleted_by", BIGINT(unsigned=True), nullable=True))
    op.create_foreign_key(FK_NAME, TABLE_NAME, "users", ["deleted_by"], ["id"])


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_constraint(FK_NAME, TABLE_NAME, type_="foreignkey")
    op.drop_column(TABLE_NAME, "deleted_by")
