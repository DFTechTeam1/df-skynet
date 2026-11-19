"""drop chat_id from df_engine_generations

Revision ID: 3a1b2c3d4e52
Revises: 3a1b2c3d4e51
Create Date: 2026-11-18 10:01:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.mysql import BIGINT

# revision identifiers, used by Alembic.
revision: str = "3a1b2c3d4e52"
down_revision: Union[str, Sequence[str], None] = "3a1b2c3d4e51"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    inspector = sa.inspect(op.get_bind())
    # FK name differs between environments, so look it up by column instead of hardcoding it.
    for fk in inspector.get_foreign_keys("df_engine_generations"):
        if fk["constrained_columns"] == ["chat_id"] and fk["name"]:
            op.drop_constraint(fk["name"], "df_engine_generations", type_="foreignkey")
    if any(c["name"] == "chat_id" for c in inspector.get_columns("df_engine_generations")):
        op.drop_column("df_engine_generations", "chat_id")


def downgrade() -> None:
    """Downgrade schema."""
    op.add_column("df_engine_generations", sa.Column("chat_id", BIGINT(unsigned=True), nullable=True))
    op.create_foreign_key(
        "fk_df_engine_generations_chat_id", "df_engine_generations", "df_engine_chat_assistants", ["chat_id"], ["id"]
    )
