"""alter df_engine_guardrail_validations: add sourceable, apikeyable, message, model

Revision ID: 3a1b2c3d4e59
Revises: 3a1b2c3d4e58
Create Date: 2026-11-20 10:01:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.mysql import BIGINT

# revision identifiers, used by Alembic.
revision: str = "3a1b2c3d4e59"
down_revision: Union[str, Sequence[str], None] = "3a1b2c3d4e58"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


TABLE_NAME = "df_engine_guardrail_validations"
SOURCEABLE_INDEX = "idx_guardrail_validations_sourceable"
APIKEYABLE_INDEX = "idx_guardrail_validations_apikeyable"


def upgrade() -> None:
    """Upgrade schema."""
    # Polymorphic: sourceable_type is the model class name of the validated row (DfEngineChatAssistants), so no FK.
    op.add_column(TABLE_NAME, sa.Column("sourceable_id", BIGINT(unsigned=True), nullable=True))
    op.add_column(TABLE_NAME, sa.Column("sourceable_type", sa.String(255), nullable=True))
    op.create_index(SOURCEABLE_INDEX, TABLE_NAME, ["sourceable_type", "sourceable_id"])
    # Polymorphic: apikeyable_type is DfEngineApiKeys | DfEngineApiKeySnapshots, so no FK.
    op.add_column(TABLE_NAME, sa.Column("apikeyable_id", BIGINT(unsigned=True), nullable=True))
    op.add_column(TABLE_NAME, sa.Column("apikeyable_type", sa.String(255), nullable=True))
    op.create_index(APIKEYABLE_INDEX, TABLE_NAME, ["apikeyable_type", "apikeyable_id"])
    # NOT NULL on a populated table: add nullable, backfill existing rows with '', then tighten. (MySQL strict mode
    # rejects a literal DEFAULT on TEXT, so a temporary server default isn't an option for `message`.) New inserts
    # must always supply both.
    op.add_column(TABLE_NAME, sa.Column("message", sa.Text, nullable=True))
    op.add_column(TABLE_NAME, sa.Column("model", sa.String(255), nullable=True))
    op.execute(f"UPDATE {TABLE_NAME} SET message = '', model = ''")
    op.alter_column(TABLE_NAME, "message", existing_type=sa.Text, nullable=False)
    op.alter_column(TABLE_NAME, "model", existing_type=sa.String(255), nullable=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column(TABLE_NAME, "model")
    op.drop_column(TABLE_NAME, "message")
    op.drop_index(APIKEYABLE_INDEX, table_name=TABLE_NAME)
    op.drop_column(TABLE_NAME, "apikeyable_type")
    op.drop_column(TABLE_NAME, "apikeyable_id")
    op.drop_index(SOURCEABLE_INDEX, table_name=TABLE_NAME)
    op.drop_column(TABLE_NAME, "sourceable_type")
    op.drop_column(TABLE_NAME, "sourceable_id")
