"""alter df engine api keys created by nullable

Revision ID: 3f99ef289e30
Revises: 5bf8a419c4fd
Create Date: 2026-08-26 14:04:58.430477

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.mysql import BIGINT


# revision identifiers, used by Alembic.
revision: str = "3f99ef289e30"
down_revision: Union[str, Sequence[str], None] = "5bf8a419c4fd"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.alter_column("df_engine_api_keys", "created_by", existing_type=BIGINT(unsigned=True), nullable=True)


def downgrade() -> None:
    """Downgrade schema."""
    op.execute("DELETE FROM df_engine_api_keys WHERE created_by IS NULL")
    op.alter_column("df_engine_api_keys", "created_by", existing_type=BIGINT(unsigned=True), nullable=False)
