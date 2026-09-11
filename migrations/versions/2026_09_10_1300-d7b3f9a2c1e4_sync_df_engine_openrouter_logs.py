"""sync df_engine_openrouter_logs to DF_ENGINE.dbml

- add generation_id (FK -> df_engine_generations.id) and attempt columns
- add idx_openrouter_logs_generation_attempt and idx_openrouter_logs_response_status
- rename the created_at/id index from the ix_ prefix to idx_

Revision ID: d7b3f9a2c1e4
Revises: c5e7a1b3d9f2
Create Date: 2026-09-10 13:00:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.mysql import BIGINT


# revision identifiers, used by Alembic.
revision: str = "d7b3f9a2c1e4"
down_revision: Union[str, Sequence[str], None] = "c5e7a1b3d9f2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

OPENROUTER_LOGS = "df_engine_openrouter_logs"
OPENROUTER_GENERATION_FK = "fk_df_engine_openrouter_logs_generation_id"


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(OPENROUTER_LOGS, sa.Column("generation_id", BIGINT(unsigned=True), nullable=True))
    op.add_column(OPENROUTER_LOGS, sa.Column("attempt", sa.Integer, nullable=True))
    op.create_foreign_key(
        OPENROUTER_GENERATION_FK,
        OPENROUTER_LOGS,
        "df_engine_generations",
        ["generation_id"],
        ["id"],
    )

    op.drop_index("ix_df_engine_openrouter_logs_created_at_id", table_name=OPENROUTER_LOGS)
    op.create_index("idx_df_engine_openrouter_logs_created_at_id", OPENROUTER_LOGS, ["created_at", "id"])
    op.create_index("idx_openrouter_logs_generation_attempt", OPENROUTER_LOGS, ["generation_id", "attempt"])
    op.create_index("idx_openrouter_logs_response_status", OPENROUTER_LOGS, ["response_status_code"])


def downgrade() -> None:
    """Downgrade schema."""
    # Drop the FK first — MySQL uses idx_openrouter_logs_generation_attempt as the
    # FK's backing index, so the index can't be dropped while the FK exists.
    op.drop_constraint(OPENROUTER_GENERATION_FK, OPENROUTER_LOGS, type_="foreignkey")

    op.drop_index("idx_openrouter_logs_response_status", table_name=OPENROUTER_LOGS)
    op.drop_index("idx_openrouter_logs_generation_attempt", table_name=OPENROUTER_LOGS)
    op.drop_index("idx_df_engine_openrouter_logs_created_at_id", table_name=OPENROUTER_LOGS)
    op.create_index("ix_df_engine_openrouter_logs_created_at_id", OPENROUTER_LOGS, ["created_at", "id"])

    op.drop_column(OPENROUTER_LOGS, "attempt")
    op.drop_column(OPENROUTER_LOGS, "generation_id")
