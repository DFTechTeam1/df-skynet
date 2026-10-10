"""backfill_exchange_rate_on_df_engine_generations

Revision ID: 9c2d7e5a1b3f
Revises: 4f1c9a7b2e5d
Create Date: 2026-10-10 11:00:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "9c2d7e5a1b3f"
down_revision: Union[str, Sequence[str], None] = "4f1c9a7b2e5d"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Fill every row with the current USD rate; 0 if the procedure is missing or errors."""
    conn = op.get_bind()
    try:
        row = conn.execute(sa.text("CALL get_currency_rate('USD')")).fetchone()
        rate = row[0] if row else 0
    except Exception:
        rate = 0
    conn.execute(sa.text("UPDATE df_engine_generations SET exchange_rate = :rate"), {"rate": rate})


def downgrade() -> None:
    """Data-only backfill; nothing to undo."""
