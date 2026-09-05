"""create df engine prompt template snapshots

Revision ID: 05a93f0e0881
Revises: 78a3d70a081e
Create Date: 2026-09-05 16:27:24.762627

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.mysql import BIGINT


# revision identifiers, used by Alembic.
revision: str = "05a93f0e0881"
down_revision: Union[str, Sequence[str], None] = "78a3d70a081e"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "df_engine_prompt_template_snapshots",
        sa.Column("id", BIGINT(unsigned=True), primary_key=True, autoincrement=True),
        sa.Column("created_at", sa.DateTime, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime, nullable=True),
        sa.Column(
            "feature_snapshot_id",
            BIGINT(unsigned=True),
            sa.ForeignKey("df_engine_feature_snapshots.id"),
            nullable=False,
        ),
        sa.Column("uid", sa.CHAR(36), nullable=False, unique=True),
        sa.Column("name", sa.String(255), nullable=True),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column("created_by", BIGINT(unsigned=True), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("updated_by", BIGINT(unsigned=True), sa.ForeignKey("users.id"), nullable=True),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table("df_engine_prompt_template_snapshots")
