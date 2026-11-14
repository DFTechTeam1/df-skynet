"""rename df_engine_elements types to type, make name and type not null

Revision ID: 80e44973dbd4
Revises: b1c2d3e4f5a6
Create Date: 2026-11-14 10:00:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "80e44973dbd4"
down_revision: Union[str, Sequence[str], None] = "b1c2d3e4f5a6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TABLE_NAME = "df_engine_elements"
ELEMENT_TYPES = sa.Enum("environment", "character", "object", "style", name="element_types")


def upgrade() -> None:
    """Upgrade schema."""
    op.execute(f"UPDATE {TABLE_NAME} SET name = 'Untitled' WHERE name IS NULL")
    op.execute(f"UPDATE {TABLE_NAME} SET types = 'environment' WHERE types IS NULL")
    op.alter_column(TABLE_NAME, "name", existing_type=sa.String(255), nullable=False)
    op.alter_column(TABLE_NAME, "types", new_column_name="type", existing_type=ELEMENT_TYPES, nullable=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.alter_column(TABLE_NAME, "type", new_column_name="types", existing_type=ELEMENT_TYPES, nullable=True)
    op.alter_column(TABLE_NAME, "name", existing_type=sa.String(255), nullable=True)
