"""refactor df_engine_chat_assistants from chat container to chat message

Revision ID: 3a1b2c3d4e54
Revises: 3a1b2c3d4e53
Create Date: 2026-11-18 10:03:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.mysql import BIGINT

# revision identifiers, used by Alembic.
revision: str = "3a1b2c3d4e54"
down_revision: Union[str, Sequence[str], None] = "3a1b2c3d4e53"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


TABLE_NAME = "df_engine_chat_assistants"
OLD_INDEX = "idx_chat_assistants_created_by_archived_at"


def upgrade() -> None:
    """Upgrade schema."""
    bind = op.get_bind()
    # ponytail: old rows are chat containers and cannot become messages (no session to attach to).
    if bind.execute(sa.text(f"SELECT COUNT(*) FROM {TABLE_NAME}")).scalar():
        raise RuntimeError(
            f"{TABLE_NAME} is not empty; old chat containers cannot be converted to messages. Clear it first."
        )

    created_by_fk = next(
        fk["name"]
        for fk in sa.inspect(bind).get_foreign_keys(TABLE_NAME)
        if fk["constrained_columns"] == ["created_by"]
    )
    op.drop_constraint(created_by_fk, TABLE_NAME, type_="foreignkey")
    op.drop_index(OLD_INDEX, TABLE_NAME)
    for col in ("placeholder", "created_by", "updated_at", "archived_at"):
        op.drop_column(TABLE_NAME, col)

    op.add_column(
        TABLE_NAME,
        sa.Column(
            "session_id",
            BIGINT(unsigned=True),
            sa.ForeignKey("df_engine_chat_sessions.id", name="fk_df_engine_chat_assistants_session_id"),
            nullable=False,
        ),
    )
    op.add_column(TABLE_NAME, sa.Column("content", sa.Text(length=4294967295), nullable=False))
    op.add_column(TABLE_NAME, sa.Column("role", sa.String(255), nullable=False))
    op.add_column(TABLE_NAME, sa.Column("model", sa.String(255), nullable=False))
    op.add_column(TABLE_NAME, sa.Column("status_code", sa.Integer, nullable=False, server_default="200"))
    op.add_column(TABLE_NAME, sa.Column("total_tokens", BIGINT(unsigned=True), nullable=False, server_default="0"))
    op.add_column(TABLE_NAME, sa.Column("cached_tokens", BIGINT(unsigned=True), nullable=False, server_default="0"))
    op.add_column(TABLE_NAME, sa.Column("cost", sa.DECIMAL(10, 2), nullable=False, server_default="0"))
    op.add_column(TABLE_NAME, sa.Column("exchange_rate", sa.DECIMAL(20, 8), nullable=False, server_default="0"))
    op.add_column(TABLE_NAME, sa.Column("has_generation_prompt", sa.Boolean, nullable=False, server_default=sa.false()))
    op.add_column(TABLE_NAME, sa.Column("sender", sa.String(255), nullable=False))


def downgrade() -> None:
    """Downgrade schema."""
    op.execute(f"DELETE FROM {TABLE_NAME}")  # messages cannot map back to old chat containers
    op.drop_constraint("fk_df_engine_chat_assistants_session_id", TABLE_NAME, type_="foreignkey")
    for col in (
        "session_id",
        "content",
        "role",
        "model",
        "status_code",
        "total_tokens",
        "cached_tokens",
        "cost",
        "exchange_rate",
        "has_generation_prompt",
        "sender",
    ):
        op.drop_column(TABLE_NAME, col)

    op.add_column(TABLE_NAME, sa.Column("placeholder", sa.Text(length=4294967295), nullable=False))
    op.add_column(
        TABLE_NAME,
        sa.Column("created_by", BIGINT(unsigned=True), sa.ForeignKey("users.id"), nullable=False),
    )
    op.add_column(
        TABLE_NAME,
        sa.Column(
            "updated_at",
            sa.DateTime,
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP"),
        ),
    )
    op.add_column(TABLE_NAME, sa.Column("archived_at", sa.DateTime, nullable=True))
    op.create_index(OLD_INDEX, TABLE_NAME, ["created_by", "archived_at"])
