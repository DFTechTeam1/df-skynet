"""sync df_engine_api_key_rotation_issues to DF_ENGINE.dbml

Rename the unresolved index from the ix_ prefix to idx_.

Revision ID: d8c4a0e6b2f5
Revises: d7b3f9a2c1e4
Create Date: 2026-09-10 13:10:00.000000

"""

from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = "d8c4a0e6b2f5"
down_revision: Union[str, Sequence[str], None] = "d7b3f9a2c1e4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

ROTATION_ISSUES = "df_engine_api_key_rotation_issues"


def upgrade() -> None:
    """Upgrade schema."""
    op.drop_index("ix_df_engine_api_key_rotation_issues_unresolved", table_name=ROTATION_ISSUES)
    op.create_index("idx_df_engine_api_key_rotation_issues_unresolved", ROTATION_ISSUES, ["resolved_at"])


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index("idx_df_engine_api_key_rotation_issues_unresolved", table_name=ROTATION_ISSUES)
    op.create_index("ix_df_engine_api_key_rotation_issues_unresolved", ROTATION_ISSUES, ["resolved_at"])
