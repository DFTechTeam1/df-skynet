"""remove minimum_allowed_transfer_knowledge_in_percent from the saved chat_assistant_settings

Revision ID: 3a1b2c3d4e64
Revises: 3a1b2c3d4e63
Create Date: 2026-11-24 12:00:00.000000

"""

from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "3a1b2c3d4e64"
down_revision: Union[str, Sequence[str], None] = "3a1b2c3d4e63"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.execute(
        "UPDATE df_engine_settings "
        "SET value = JSON_REMOVE(value, '$.minimum_allowed_transfer_knowledge_in_percent') "
        "WHERE code = 'admin_setting' AND `key` = 'chat_assistant_settings' AND JSON_VALID(value)"
    )


def downgrade() -> None:
    """Downgrade schema."""
    # the removed key is not restored: the app no longer reads it
