"""alter df_engine_guardrail_validations: replace model (string) with model_id (FK -> df_engine_model_options.id)

Revision ID: 3a1b2c3d4e5d
Revises: 3a1b2c3d4e5c
Create Date: 2026-11-20 10:05:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.mysql import BIGINT

# revision identifiers, used by Alembic.
revision: str = "3a1b2c3d4e5d"
down_revision: Union[str, Sequence[str], None] = "3a1b2c3d4e5c"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


TABLE_NAME = "df_engine_guardrail_validations"
FK_NAME = "fk_guardrail_validations_model_id"


def upgrade() -> None:
    """Upgrade schema."""
    # Nullable: legacy rows whose `model` text matches no catalog row (deleted, renamed or '') keep NULL.
    op.add_column(TABLE_NAME, sa.Column("model_id", BIGINT(unsigned=True), nullable=True))
    op.create_foreign_key(FK_NAME, TABLE_NAME, "df_engine_model_options", ["model_id"], ["id"])
    # The old text was the provider model id (e.g. "mistralai/..."); guardrail validations only call text models.
    op.execute(
        f"UPDATE {TABLE_NAME} t JOIN df_engine_model_options m ON m.model_id = t.model AND m.type = 'text' "
        "SET t.model_id = m.id"
    )
    op.drop_column(TABLE_NAME, "model")


def downgrade() -> None:
    """Downgrade schema."""
    op.add_column(TABLE_NAME, sa.Column("model", sa.String(255), nullable=True))
    op.execute(
        f"UPDATE {TABLE_NAME} t LEFT JOIN df_engine_model_options m ON m.id = t.model_id "
        "SET t.model = COALESCE(m.model_id, '')"
    )
    op.alter_column(TABLE_NAME, "model", existing_type=sa.String(255), nullable=False)
    op.drop_constraint(FK_NAME, TABLE_NAME, type_="foreignkey")
    op.drop_column(TABLE_NAME, "model_id")
