"""add element_id to df_engine_upload_files

Revision ID: b1c2d3e4f5a6
Revises: a0b1c2d3e4f5
Create Date: 2026-11-12 10:02:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.mysql import BIGINT

# revision identifiers, used by Alembic.
revision: str = "b1c2d3e4f5a6"
down_revision: Union[str, Sequence[str], None] = "a0b1c2d3e4f5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TABLE_NAME = "df_engine_upload_files"
FK_NAME = "fk_df_engine_upload_files_element_id"


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(TABLE_NAME, sa.Column("element_id", BIGINT(unsigned=True), nullable=True))
    op.create_foreign_key(FK_NAME, TABLE_NAME, "df_engine_elements", ["element_id"], ["id"])


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_constraint(FK_NAME, TABLE_NAME, type_="foreignkey")
    op.drop_column(TABLE_NAME, "element_id")
