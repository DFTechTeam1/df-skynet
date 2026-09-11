"""create df_engine_generation_reconciliation_issues

Revision ID: f8b9d0e1a2c3
Revises: e7a8c9d0f1b2
Create Date: 2026-09-10 14:22:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.mysql import BIGINT


# revision identifiers, used by Alembic.
revision: str = "f8b9d0e1a2c3"
down_revision: Union[str, Sequence[str], None] = "e7a8c9d0f1b2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TABLE_NAME = "df_engine_generation_reconciliation_issues"


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        TABLE_NAME,
        sa.Column("id", BIGINT(unsigned=True), primary_key=True, autoincrement=True),
        sa.Column("created_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
        sa.Column("uid", sa.CHAR(36), nullable=False, unique=True),
        sa.Column("generation_id", BIGINT(unsigned=True), sa.ForeignKey("df_engine_generations.id"), nullable=False),
        sa.Column(
            "upload_id",
            BIGINT(unsigned=True),
            sa.ForeignKey("df_engine_generation_uploads.id"),
            nullable=True,
        ),
        sa.Column("issue_type", sa.String(50), nullable=False),
        sa.Column("detail", sa.Text, nullable=True),
        sa.Column("resolved_at", sa.DateTime, nullable=True),
        sa.Column("resolved_by", BIGINT(unsigned=True), sa.ForeignKey("users.id"), nullable=True),
    )
    op.create_index("idx_reconciliation_issues_generation_id", TABLE_NAME, ["generation_id"])
    op.create_index("idx_reconciliation_issues_unresolved", TABLE_NAME, ["resolved_at"])


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table(TABLE_NAME)
