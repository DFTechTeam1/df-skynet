"""sync df_engine_model_options to DF_ENGINE.dbml

- add deleted_at (nullable)
- rename the composite UNIQUE (model_id, type) to idx_model_options_model_id
  (same columns — a model_id can appear under more than one usage type)
- the ck_df_engine_model_options_is_main_requires_enabled CHECK stays as-is

Revision ID: c3e4a5b6d7f8
Revises: b2d3f4a5c6e7
Create Date: 2026-09-10 14:02:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "c3e4a5b6d7f8"
down_revision: Union[str, Sequence[str], None] = "b2d3f4a5c6e7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TABLE_NAME = "df_engine_model_options"
OLD_UNIQUE = "uq_df_engine_model_options_model_id_type"
NEW_UNIQUE_INDEX = "idx_model_options_model_id"


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(TABLE_NAME, sa.Column("deleted_at", sa.DateTime, nullable=True))
    # Rename the composite unique to the DBML name; keep (model_id, type) — the
    # same model_id legitimately appears under more than one usage type
    # (multimodal models listed on several OpenRouter modality endpoints).
    op.drop_constraint(OLD_UNIQUE, TABLE_NAME, type_="unique")
    op.create_index(NEW_UNIQUE_INDEX, TABLE_NAME, ["model_id", "type"], unique=True)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(NEW_UNIQUE_INDEX, table_name=TABLE_NAME)
    op.create_unique_constraint(OLD_UNIQUE, TABLE_NAME, ["model_id", "type"])
    op.drop_column(TABLE_NAME, "deleted_at")
