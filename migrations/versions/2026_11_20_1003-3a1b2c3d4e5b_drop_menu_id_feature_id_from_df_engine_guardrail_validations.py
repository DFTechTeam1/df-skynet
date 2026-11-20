"""drop menu_id, feature_id from df_engine_guardrail_validations

Replaced by the polymorphic sourceable_type / sourceable_id columns.

Revision ID: 3a1b2c3d4e5b
Revises: 3a1b2c3d4e5a
Create Date: 2026-11-20 10:03:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.mysql import BIGINT

# revision identifiers, used by Alembic.
revision: str = "3a1b2c3d4e5b"
down_revision: Union[str, Sequence[str], None] = "3a1b2c3d4e5a"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


TABLE_NAME = "df_engine_guardrail_validations"
# column -> (referenced table, FK name used on downgrade)
COLUMNS = {
    "menu_id": ("df_engine_menus", "fk_guardrail_validations_menu_id"),
    "feature_id": ("df_engine_features", "fk_guardrail_validations_feature_id"),
}


def upgrade() -> None:
    """Upgrade schema."""
    # The FKs were created unnamed (MySQL auto-names them *_ibfk_N), so look the names up before dropping.
    fks = sa.inspect(op.get_bind()).get_foreign_keys(TABLE_NAME)
    for column in COLUMNS:
        for fk in fks:
            if fk["constrained_columns"] == [column]:
                op.drop_constraint(fk["name"], TABLE_NAME, type_="foreignkey")
        op.drop_column(TABLE_NAME, column)


def downgrade() -> None:
    """Downgrade schema."""
    # ponytail: re-added nullable — the dropped values are gone, so NOT NULL can't be restored on a populated table.
    for column, (ref_table, fk_name) in COLUMNS.items():
        op.add_column(TABLE_NAME, sa.Column(column, BIGINT(unsigned=True), nullable=True))
        op.create_foreign_key(fk_name, TABLE_NAME, ref_table, [column], ["id"])
