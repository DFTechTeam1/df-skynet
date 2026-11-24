"""ON DELETE CASCADE on df_engine_upload_file_references.file_id and df_engine_chat_references.attachment_id,
so deleting an upload file (and its attachments) drops the links to them

Revision ID: 3a1b2c3d4e63
Revises: 3a1b2c3d4e61
Create Date: 2026-11-24 11:00:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "3a1b2c3d4e63"
down_revision: Union[str, Sequence[str], None] = "3a1b2c3d4e61"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# (table, column, referenced table)
FKS = [
    ("df_engine_upload_file_references", "file_id", "df_engine_upload_files"),
    ("df_engine_chat_references", "attachment_id", "df_engine_attachments"),
]


def _replace_fk(table: str, column: str, ref_table: str, ondelete: Union[str, None]) -> None:
    # the original FKs were created unnamed (MySQL auto-names `<table>_ibfk_N`): look the name up
    for fk in sa.inspect(op.get_bind()).get_foreign_keys(table):
        if fk["constrained_columns"] == [column]:
            op.drop_constraint(fk["name"], table, type_="foreignkey")
    op.create_foreign_key(f"fk_{table}_{column}", table, ref_table, [column], ["id"], ondelete=ondelete)


def upgrade() -> None:
    """Upgrade schema."""
    for table, column, ref_table in FKS:
        _replace_fk(table, column, ref_table, "CASCADE")


def downgrade() -> None:
    """Downgrade schema."""
    for table, column, ref_table in FKS:
        _replace_fk(table, column, ref_table, None)
