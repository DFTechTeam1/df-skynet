"""Insert 3 chained sample rows (1 -> 2 -> 3) and print them with a one-level `childrens` list.
Run: uv run python -m sample_results_tree   (from erp-engine root)
"""

import json
from hashlib import md5

from sqlalchemy.orm import selectinload

from services.mysql import get_sync_db, query_sync
from services.mysql.model import DfEngineGenerationResults as R

PREFIX = "sample_tree_"
# (key, parent_key, is_main, version)
SEED = [
    ("1", None, True, 1),
    ("2", "1", True, 1),
    ("3", "2", True, 1),
    ("2b", "1", False, 2),
    ("2c", "1", False, 3),
    ("3b", "2", False, 2),
    ("4", None, True, 1),
    ("5", "4", True, 1),
]


with get_sync_db() as s:
    ids = {}
    for n, (key, parent, is_main, version) in enumerate(SEED, 1):  # upsert by name -> idempotent
        name = f"{PREFIX}{key}"
        row = query_sync(s, R, filters=(R.name == name,), fetch_one=True) or R(name=name)
        row.path, row.size, row.md5 = f"/tmp/{name}.png", 100 * n, md5(name.encode()).hexdigest()
        row.is_main, row.version, row.parent_id = is_main, version, ids.get(parent)
        s.add(row)
        s.flush()  # need id for the children below
        ids[key] = row.id

    rows = query_sync(s, R, filters=(R.children.any(R.id == 156),), options=(selectinload(R.children),))
    print(
        json.dumps(
            [
                {"id": r.id, **r.model_dump(), "childrens": [{"id": c.id, **c.model_dump()} for c in r.children]}
                for r in rows
            ],
            indent=2,
            default=str,
        )
    )
