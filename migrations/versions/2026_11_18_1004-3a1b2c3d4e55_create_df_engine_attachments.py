"""create df_engine_attachments

Revision ID: 3a1b2c3d4e55
Revises: 3a1b2c3d4e54
Create Date: 2026-11-18 10:04:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.mysql import BIGINT

# revision identifiers, used by Alembic.
revision: str = "3a1b2c3d4e55"
down_revision: Union[str, Sequence[str], None] = "3a1b2c3d4e54"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


TABLE_NAME = "df_engine_attachments"


def upgrade() -> None:
    """Upgrade schema."""
    # Polymorphic: sourceable_type is the model class name (DfEngineUploadFiles | DfEngineGenerationResults), so no FK.
    op.create_table(
        TABLE_NAME,
        sa.Column("id", BIGINT(unsigned=True), primary_key=True, autoincrement=True),
        sa.Column("sourceable_id", BIGINT(unsigned=True), nullable=False),
        sa.Column("sourceable_type", sa.String(255), nullable=False),
    )
    op.create_index("idx_attachments_sourceable", TABLE_NAME, ["sourceable_type", "sourceable_id"])


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table(TABLE_NAME)
