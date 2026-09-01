"""updated df engine api keys

Revision ID: b10e09cd766e
Revises: b8c9d0e1f2a3
Create Date: 2026-08-21 11:37:35.784456

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.mysql import BIGINT, DECIMAL


# revision identifiers, used by Alembic.
revision: str = "b10e09cd766e"
down_revision: Union[str, Sequence[str], None] = "b8c9d0e1f2a3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Added new columns
    op.add_column("df_engine_api_keys", sa.Column("hash", sa.String(255), nullable=True))
    op.add_column("df_engine_api_keys", sa.Column("employee_name", sa.String(255), nullable=True))
    op.add_column(
        "df_engine_api_keys",
        sa.Column("is_main", sa.Boolean(), nullable=False, server_default=sa.false()),
    )

    # Modify existing columns
    op.alter_column(
        "df_engine_api_keys",
        "employee_id",
        existing_type=BIGINT(unsigned=True),
        nullable=True,
    )
    op.alter_column(
        "df_engine_api_keys",
        "limit_usage",
        new_column_name="limit",
        existing_type=DECIMAL(10, 2),
        existing_nullable=True,
    )

    op.alter_column(
        "df_engine_api_keys",
        "key",
        existing_type=sa.Text(),
        type_=sa.String(255),
        existing_nullable=False,
    )
    op.execute(
        """
        UPDATE df_engine_api_keys t
        JOIN (
            SELECT id, ROW_NUMBER() OVER (PARTITION BY `key` ORDER BY id) AS rn
            FROM df_engine_api_keys
        ) ranked ON ranked.id = t.id
        SET t.`key` = CONCAT(LEFT(t.`key`, 245), '-', t.id)
        WHERE ranked.rn > 1
        """
    )
    op.create_unique_constraint("uq_df_engine_api_keys_key", "df_engine_api_keys", ["key"])

    # Drop existing columns
    op.drop_column("df_engine_api_keys", "deleted_at")
    op.drop_column("df_engine_api_keys", "is_active")


def downgrade() -> None:
    """Downgrade schema. Written to be safe to re-run — an earlier attempt may have
    partially applied before failing on the employee_id NOT NULL step."""
    bind = op.get_bind()

    def _has_col(col: str) -> bool:
        return bool(
            bind.execute(
                sa.text(
                    "SELECT 1 FROM information_schema.columns WHERE table_schema = DATABASE() "
                    "AND table_name = 'df_engine_api_keys' AND column_name = :c"
                ),
                {"c": col},
            ).scalar()
        )

    def _has_constraint(name: str) -> bool:
        return bool(
            bind.execute(
                sa.text(
                    "SELECT 1 FROM information_schema.table_constraints WHERE table_schema = DATABASE() "
                    "AND table_name = 'df_engine_api_keys' AND constraint_name = :n"
                ),
                {"n": name},
            ).scalar()
        )

    if _has_constraint("uq_df_engine_api_keys_key"):
        op.drop_constraint("uq_df_engine_api_keys_key", "df_engine_api_keys", type_="unique")

    op.alter_column(
        "df_engine_api_keys",
        "key",
        existing_type=sa.String(255),
        type_=sa.Text(),
        existing_nullable=False,
    )

    if not _has_col("deleted_at"):
        op.add_column("df_engine_api_keys", sa.Column("deleted_at", sa.DateTime(), nullable=True))

    if _has_col("limit"):
        op.alter_column(
            "df_engine_api_keys",
            "limit",
            new_column_name="limit_usage",
            existing_type=DECIMAL(10, 2),
            existing_nullable=True,
        )

    # employee_id went nullable in upgrade(); rows created since (incl. test-factory
    # rows) may hold NULL. Drop them before restoring NOT NULL.
    op.execute("DELETE FROM df_engine_api_keys WHERE employee_id IS NULL")
    op.alter_column(
        "df_engine_api_keys",
        "employee_id",
        existing_type=BIGINT(unsigned=True),
        nullable=False,
    )

    if not _has_col("is_active"):
        op.add_column(
            "df_engine_api_keys",
            sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        )
    for col in ("is_main", "employee_name", "hash"):
        if _has_col(col):
            op.drop_column("df_engine_api_keys", col)
