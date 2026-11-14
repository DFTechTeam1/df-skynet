"""drop element_id from df_engine_upload_files

Revision ID: f2b3c4d5e6a7
Revises: e1a2b3c4d5f6
Create Date: 2026-11-14 11:01:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.mysql import BIGINT

# revision identifiers, used by Alembic.
revision: str = "f2b3c4d5e6a7"
down_revision: Union[str, Sequence[str], None] = "e1a2b3c4d5f6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TABLE_NAME = "df_engine_upload_files"
FK_NAME = "fk_df_engine_upload_files_element_id"


def upgrade() -> None:
    """Upgrade schema."""
    op.drop_constraint(FK_NAME, TABLE_NAME, type_="foreignkey")
    op.drop_column(TABLE_NAME, "element_id")


def downgrade() -> None:
    """Downgrade schema."""
    op.add_column(TABLE_NAME, sa.Column("element_id", BIGINT(unsigned=True), nullable=True))
    op.create_foreign_key(FK_NAME, TABLE_NAME, "df_engine_elements", ["element_id"], ["id"])
