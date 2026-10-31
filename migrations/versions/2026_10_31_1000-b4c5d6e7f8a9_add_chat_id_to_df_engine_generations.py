"""add chat_id to df_engine_generations

Revision ID: b4c5d6e7f8a9
Revises: c5d6e7f8a9b0
Create Date: 2026-10-31 10:00:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.mysql import BIGINT

# revision identifiers, used by Alembic.
revision: str = "b4c5d6e7f8a9"
down_revision: Union[str, Sequence[str], None] = "c5d6e7f8a9b0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column("df_engine_generations", sa.Column("chat_id", BIGINT(unsigned=True), nullable=True))
    op.create_foreign_key(
        "fk_df_engine_generations_chat_id", "df_engine_generations", "df_engine_chat_assistants", ["chat_id"], ["id"]
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_constraint("fk_df_engine_generations_chat_id", "df_engine_generations", type_="foreignkey")
    op.drop_column("df_engine_generations", "chat_id")
