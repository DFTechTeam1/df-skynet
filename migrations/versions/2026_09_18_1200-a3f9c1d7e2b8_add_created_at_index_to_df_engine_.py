"""add created_at index to df_engine_generations

Revision ID: a3f9c1d7e2b8
Revises: 39ffbd62abca
Create Date: 2026-09-18 12:00:00.000000

"""

from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a3f9c1d7e2b8"
down_revision: Union[str, Sequence[str], None] = "39ffbd62abca"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_index("idx_generations_created_at", "df_engine_generations", ["created_at"])


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index("idx_generations_created_at", table_name="df_engine_generations")
