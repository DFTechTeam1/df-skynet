"""drop feature_id from df_engine_chat_sessions

Sessions are listed per menu and their system prompt comes from the initialize_session feature,
so the session no longer belongs to a feature.

Revision ID: 3a1b2c3d4e71
Revises: 3a1b2c3d4e70
Create Date: 2026-11-24 15:00:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.mysql import BIGINT

# revision identifiers, used by Alembic.
revision: str = "3a1b2c3d4e71"
down_revision: Union[str, Sequence[str], None] = "3a1b2c3d4e70"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


TABLE_NAME = "df_engine_chat_sessions"
COLUMN = "feature_id"
FK_NAME = "fk_chat_sessions_feature_id"


def upgrade() -> None:
    """Upgrade schema."""
    # The FK was created unnamed (MySQL auto-names it *_ibfk_N), so look the name up before dropping.
    for fk in sa.inspect(op.get_bind()).get_foreign_keys(TABLE_NAME):
        if fk["constrained_columns"] == [COLUMN]:
            op.drop_constraint(fk["name"], TABLE_NAME, type_="foreignkey")
    op.drop_column(TABLE_NAME, COLUMN)


def downgrade() -> None:
    """Downgrade schema."""
    # ponytail: re-added nullable — the dropped values are gone, so NOT NULL can't be restored on a populated table.
    op.add_column(TABLE_NAME, sa.Column(COLUMN, BIGINT(unsigned=True), nullable=True))
    op.create_foreign_key(FK_NAME, TABLE_NAME, "df_engine_features", [COLUMN], ["id"])
