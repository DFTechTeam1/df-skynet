"""add full_prompt to df_engine_generations

Revision ID: 39ffbd62abca
Revises: d211c2e23574
Create Date: 2026-09-18 11:00:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "39ffbd62abca"
down_revision: Union[str, Sequence[str], None] = "d211c2e23574"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column("df_engine_generations", sa.Column("full_prompt", sa.Text(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("df_engine_generations", "full_prompt")
