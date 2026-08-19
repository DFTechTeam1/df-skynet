"""create df engine api keys

Revision ID: 5cf9c7f977f7
Revises: 145f3944f4ec
Create Date: 2026-08-18 21:38:39.099496

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.mysql import BIGINT, DECIMAL


# revision identifiers, used by Alembic.
revision: str = "5cf9c7f977f7"
down_revision: Union[str, Sequence[str], None] = "145f3944f4ec"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "df_engine_api_keys",
        sa.Column("id", BIGINT(unsigned=True), primary_key=True, autoincrement=True),
        sa.Column("created_at", sa.DateTime, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime, nullable=True),
        sa.Column("expired_at", sa.DateTime, nullable=True),
        sa.Column("limit_usage", DECIMAL(10, 2), nullable=True),
        sa.Column("limit_reset", sa.String(20), nullable=True),
        sa.Column("uid", sa.CHAR(36), nullable=False, unique=True),
        sa.Column("key", sa.Text, nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column(
            "employee_id",
            BIGINT(unsigned=True),
            sa.ForeignKey("employees.id"),
            nullable=False,
        ),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default=sa.true()),
        sa.Column(
            "created_by",
            BIGINT(unsigned=True),
            sa.ForeignKey("users.id"),
            nullable=False,
        ),
        sa.Column(
            "updated_by",
            BIGINT(unsigned=True),
            sa.ForeignKey("users.id"),
            nullable=True,
        ),
        # `name` has no DB-level unique constraint: it must stay unique only among
        # non-deleted rows (soft-deleting a key frees its name for reuse), and MySQL
        # has no partial/filtered unique index. Enforced instead by the controller
        # checking for an existing non-deleted row with the same name before insert/update.
        sa.Column("deleted_at", sa.DateTime, nullable=True),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table("df_engine_api_keys")
