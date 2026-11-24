"""add will_generate_prompt to df_engine_chat_assistants

True on an assistant reply that asks the user whether to write the generation prompt (the FE pop-up trigger).

Revision ID: 3a1b2c3d4e72
Revises: 3a1b2c3d4e71
Create Date: 2026-11-24 15:01:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "3a1b2c3d4e72"
down_revision: Union[str, Sequence[str], None] = "3a1b2c3d4e71"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


TABLE_NAME = "df_engine_chat_assistants"
COLUMN = "will_generate_prompt"


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(TABLE_NAME, sa.Column(COLUMN, sa.Boolean(), nullable=False, server_default=sa.false()))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column(TABLE_NAME, COLUMN)
