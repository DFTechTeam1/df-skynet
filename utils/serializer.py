from collections.abc import Mapping, Sequence
from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from typing import Any
from sqlalchemy import Row, RowMapping
from sqlalchemy.orm import attributes


def to_json_safe(data: Any) -> Any:
    """Recursively convert non-ORM values (dict/list/tuple/Decimal/datetime/date/Enum)
    into JSON-safe equivalents. Anything else is returned unchanged.

    This is the leaf-level converter `serialize()` falls back to once it has
    finished unwrapping ORM objects, Rows, and containers.
    """
    if isinstance(data, dict):
        return {k: to_json_safe(v) for k, v in data.items()}

    if isinstance(data, (list, tuple)):
        return [to_json_safe(v) for v in data]

    if isinstance(data, Decimal):
        return float(data)

    if isinstance(data, (datetime, date)):
        return data.isoformat()

    if isinstance(data, Enum):
        return data.value

    return data


def serialize(data: Any) -> Any:
    """Public entrypoint — see the module docstring for full behavior and caveats.

    Accepts a single ORM instance, a list/tuple of them, a Core `Row`/`RowMapping`,
    or a plain value, and returns JSON-safe `dict`/`list`/primitive data.
    """
    return _serialize(data, seen=set())


def _serialize(data: Any, seen: set[int]) -> Any:
    """Recursion worker. `seen` holds `id()`s of ORM objects on the current
    traversal path only (a fresh branch is created per relationship hop, not
    shared across siblings), so it detects real cycles without falsely
    flagging the same object appearing twice in unrelated branches.
    """

    if hasattr(data, "__table__"):
        obj_id = id(data)
        if obj_id in seen:
            return None
        seen = seen | {obj_id}

        result: dict[str, Any] = {}
        state = attributes.instance_state(data)

        for attr in data.__mapper__.column_attrs:
            if attr.key in state.unloaded:
                continue
            result[attr.key] = _serialize(getattr(data, attr.key), seen)

        for rel in data.__mapper__.relationships:
            if rel.key in state.unloaded:
                continue

            value = getattr(data, rel.key)
            if rel.uselist:
                result[rel.key] = _serialize(value or [], seen)
            else:
                result[rel.key] = _serialize(value, seen)

        return result

    if isinstance(data, (Row, RowMapping, Mapping)):
        return {k: _serialize(v, seen) for k, v in dict(data).items()}

    if isinstance(data, (list, tuple, Sequence)) and not isinstance(data, (str, bytes)):
        return [_serialize(v, seen) for v in data]

    return to_json_safe(data)
