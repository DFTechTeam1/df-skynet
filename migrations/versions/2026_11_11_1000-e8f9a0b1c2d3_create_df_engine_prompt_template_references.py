"""create df_engine_prompt_template_references

Revision ID: e8f9a0b1c2d3
Revises: d7e8f9a0b1c2
Create Date: 2026-11-11 10:00:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.mysql import BIGINT

# revision identifiers, used by Alembic.
revision: str = "e8f9a0b1c2d3"
down_revision: Union[str, Sequence[str], None] = "d7e8f9a0b1c2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "df_engine_prompt_template_references",
        sa.Column("id", BIGINT(unsigned=True), primary_key=True, autoincrement=True),
        sa.Column(
            "main_template_id",
            BIGINT(unsigned=True),
            sa.ForeignKey("df_engine_prompt_templates.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "reference_id",
            BIGINT(unsigned=True),
            sa.ForeignKey("df_engine_prompt_templates.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.UniqueConstraint("main_template_id", "reference_id", name="idx_prompt_template_references_unique_pair"),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table("df_engine_prompt_template_references")
