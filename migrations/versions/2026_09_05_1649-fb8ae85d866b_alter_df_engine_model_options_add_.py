"""alter df engine model options add deleted at deleted by

Revision ID: fb8ae85d866b
Revises: 05a93f0e0881
Create Date: 2026-09-05 16:49:14.577277

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.mysql import BIGINT


# revision identifiers, used by Alembic.
revision: str = "fb8ae85d866b"
down_revision: Union[str, Sequence[str], None] = "05a93f0e0881"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column("df_engine_model_options", sa.Column("deleted_at", sa.DateTime, nullable=True))
    op.add_column("df_engine_model_options", sa.Column("deleted_by", BIGINT(unsigned=True), nullable=True))
    op.create_foreign_key(
        "fk_df_engine_model_options_deleted_by",
        "df_engine_model_options",
        "users",
        ["deleted_by"],
        ["id"],
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_constraint("fk_df_engine_model_options_deleted_by", "df_engine_model_options", type_="foreignkey")
    op.drop_column("df_engine_model_options", "deleted_by")
    op.drop_column("df_engine_model_options", "deleted_at")
