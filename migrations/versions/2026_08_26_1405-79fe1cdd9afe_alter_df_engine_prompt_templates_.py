"""alter df engine prompt templates created by nullable

Revision ID: 79fe1cdd9afe
Revises: 0d43edbbcfb9
Create Date: 2026-08-26 14:05:00.503170

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.mysql import BIGINT


# revision identifiers, used by Alembic.
revision: str = "79fe1cdd9afe"
down_revision: Union[str, Sequence[str], None] = "0d43edbbcfb9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.alter_column("df_engine_prompt_templates", "created_by", existing_type=BIGINT(unsigned=True), nullable=True)


def downgrade() -> None:
    """Downgrade schema."""
    op.execute(
        "DELETE FROM df_engine_feature_prompt_mappings "
        "WHERE template_id IN (SELECT id FROM df_engine_prompt_templates WHERE created_by IS NULL)"
    )
    op.execute("DELETE FROM df_engine_prompt_templates WHERE created_by IS NULL")
    op.alter_column("df_engine_prompt_templates", "created_by", existing_type=BIGINT(unsigned=True), nullable=False)
