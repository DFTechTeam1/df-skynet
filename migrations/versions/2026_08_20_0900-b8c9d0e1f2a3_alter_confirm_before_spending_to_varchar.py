"""alter confirm_before_spending to varchar

Revision ID: b8c9d0e1f2a3
Revises: a7b8c9d0e1f2
Create Date: 2026-08-20 09:00:00.000000

confirm_before_spending moves from DECIMAL(10,2) to a varchar enum
("over_0.5" | "off" | "over_0.1" | "always"). Existing decimal values
can't be reliably mapped to the new enum options, so any row that
already had a value is reformatted to "always".
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.mysql import DECIMAL


# revision identifiers, used by Alembic.
revision: str = "b8c9d0e1f2a3"
down_revision: Union[str, Sequence[str], None] = "a7b8c9d0e1f2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.alter_column(
        "df_engine_preferences",
        "confirm_before_spending",
        existing_type=DECIMAL(10, 2),
        type_=sa.String(255),
        existing_nullable=False,
        server_default="always",
    )
    op.execute("UPDATE df_engine_preferences SET confirm_before_spending = 'always'")


def downgrade() -> None:
    """Downgrade schema."""
    op.execute("UPDATE df_engine_preferences SET confirm_before_spending = '0.50'")
    op.alter_column(
        "df_engine_preferences",
        "confirm_before_spending",
        existing_type=sa.String(255),
        type_=DECIMAL(10, 2),
        existing_nullable=False,
        server_default="0.50",
    )
