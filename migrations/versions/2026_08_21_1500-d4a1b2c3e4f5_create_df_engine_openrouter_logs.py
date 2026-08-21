"""create df engine openrouter logs

Revision ID: d4a1b2c3e4f5
Revises: c21f4a9d8b3e
Create Date: 2026-08-21 15:00:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.mysql import BIGINT


# revision identifiers, used by Alembic.
revision: str = "d4a1b2c3e4f5"
down_revision: Union[str, Sequence[str], None] = "c21f4a9d8b3e"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "df_engine_openrouter_logs",
        sa.Column("id", BIGINT(unsigned=True), primary_key=True, autoincrement=True),
        sa.Column("created_at", sa.DateTime, server_default=sa.func.now()),
        sa.Column("uid", sa.CHAR(36), nullable=False, unique=True),
        sa.Column("name", sa.String(255), nullable=True),
        sa.Column("method", sa.String(10), nullable=False),
        sa.Column("endpoint", sa.String(255), nullable=False),
        sa.Column("request_headers", sa.JSON, nullable=True),
        sa.Column("request_payload", sa.JSON, nullable=True),
        sa.Column("response_status_code", sa.Integer, nullable=True),
        sa.Column("response_headers", sa.JSON, nullable=True),
        sa.Column("response_body", sa.JSON, nullable=True),
        sa.Column("error_message", sa.Text, nullable=True),
        sa.Column("duration_ms", sa.Integer, nullable=True),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table("df_engine_openrouter_logs")
