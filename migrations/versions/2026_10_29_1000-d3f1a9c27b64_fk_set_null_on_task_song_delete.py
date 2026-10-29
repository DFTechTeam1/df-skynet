"""task_id/song_id FKs: ON DELETE SET NULL, so the owning service can delete tasks/songs

Revision ID: d3f1a9c27b64
Revises: a1b2c3d4e5f7
Create Date: 2026-10-29 10:00:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "d3f1a9c27b64"
down_revision: Union[str, Sequence[str], None] = "a1b2c3d4e5f7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# (table, column, referenced table)
FKS = [
    ("df_engine_generations", "task_id", "project_tasks"),
    ("df_engine_generations", "song_id", "project_song_lists"),
    ("df_engine_upload_files", "task_id", "project_tasks"),
    ("df_engine_upload_files", "song_id", "project_song_lists"),
]


def _replace_fk(table: str, column: str, ref_table: str, ondelete: Union[str, None]) -> None:
    # older FKs were created unnamed (MySQL auto-names `<table>_ibfk_N`): look the name up
    for fk in sa.inspect(op.get_bind()).get_foreign_keys(table):
        if fk["constrained_columns"] == [column]:
            op.drop_constraint(fk["name"], table, type_="foreignkey")
    op.create_foreign_key(f"fk_{table}_{column}", table, ref_table, [column], ["id"], ondelete=ondelete)


def upgrade() -> None:
    """Upgrade schema."""
    for table, column, ref_table in FKS:
        _replace_fk(table, column, ref_table, "SET NULL")


def downgrade() -> None:
    """Downgrade schema."""
    for table, column, ref_table in FKS:
        _replace_fk(table, column, ref_table, None)
