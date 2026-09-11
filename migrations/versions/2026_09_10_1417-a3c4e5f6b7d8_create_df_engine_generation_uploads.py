"""create df_engine_generation_uploads

Revision ID: a3c4e5f6b7d8
Revises: f2b3d4e5a6c7
Create Date: 2026-09-10 14:17:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.mysql import BIGINT


# revision identifiers, used by Alembic.
revision: str = "a3c4e5f6b7d8"
down_revision: Union[str, Sequence[str], None] = "f2b3d4e5a6c7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TABLE_NAME = "df_engine_generation_uploads"
UPLOAD_STATUSES = sa.Enum("pending", "success", "failed", name="upload_statuses")


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        TABLE_NAME,
        sa.Column("id", BIGINT(unsigned=True), primary_key=True, autoincrement=True),
        sa.Column("created_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
        sa.Column("uploaded_at", sa.DateTime, nullable=True),
        sa.Column("generation_id", BIGINT(unsigned=True), sa.ForeignKey("df_engine_generations.id"), nullable=False),
        sa.Column("upload_status", UPLOAD_STATUSES, nullable=False, server_default="pending"),
        sa.Column("sweep_attempts", sa.Integer, nullable=False, server_default="0"),
        sa.Column("needs_reconciliation", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("reconciled_at", sa.DateTime, nullable=True),
    )
    op.create_index("idx_generation_uploads_generation_id", TABLE_NAME, ["generation_id"], unique=True)
    op.create_index("idx_generation_uploads_status_uploaded_at", TABLE_NAME, ["upload_status", "uploaded_at"])
    op.create_index("idx_generation_uploads_needs_reconciliation", TABLE_NAME, ["needs_reconciliation"])


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table(TABLE_NAME)
    UPLOAD_STATUSES.drop(op.get_bind(), checkfirst=True)
