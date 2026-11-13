"""rename df_engine_generations.prompt to raw_prompt, add finalized_prompt

Revision ID: f9a0b1c2d3e4
Revises: e8f9a0b1c2d3
Create Date: 2026-11-13 10:00:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "f9a0b1c2d3e4"
down_revision: Union[str, Sequence[str], None] = "e8f9a0b1c2d3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.alter_column(
        "df_engine_generations",
        "prompt",
        new_column_name="raw_prompt",
        existing_type=sa.Text(),
        existing_nullable=False,
    )
    op.add_column("df_engine_generations", sa.Column("finalized_prompt", sa.Text(), nullable=True))
    op.execute("UPDATE df_engine_generations SET finalized_prompt = raw_prompt")
    op.execute(
        "UPDATE df_engine_generations SET finalized_prompt = response WHERE kind = 'enhancer' AND response IS NOT NULL"
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("df_engine_generations", "finalized_prompt")
    op.alter_column(
        "df_engine_generations",
        "raw_prompt",
        new_column_name="prompt",
        existing_type=sa.Text(),
        existing_nullable=False,
    )
