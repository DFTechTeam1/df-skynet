from datetime import datetime
from typing import Optional, Any


def format_creator(user: Optional[dict[str, Any]]) -> Optional[dict[str, Any]]:
    """Reshape a serialized `Users` row (as produced by `utils.serializer.serialize`,
    with its `employees` relationship eager-loaded) into `{"image", "nickname"}`.

    Used for both `created_by_user` and `updated_by_user` on a prompt template,
    hence the generic "creator" naming rather than tying it to one field.

    Args:
        user: The serialized `Users` dict (with a nested `employees` dict), or
            `None` if the relationship wasn't set (e.g. `updated_by_user` on a
            record nobody has updated yet).

    Returns:
        `{"image": ..., "nickname": ...}`, or `None` if `user` is `None`.
        `nickname` is `None` if the user has no linked `employees` row.
    """
    if user is None:
        return None
    employees = user.get("employees") or {}
    return {
        "image": user.get("image"),
        "nickname": employees.get("nickname"),
    }


def format_datetime(value: Optional[datetime | str]) -> Optional[str]:
    """Format a datetime (or an ISO-8601 string, e.g. from `utils.serializer.serialize`)
    as 'DD Month YYYY, HH:MM' (e.g. '17 August 2026, 00:07').

    Args:
        value: A `datetime`, an ISO-8601 string, or `None`.

    Returns:
        The formatted display string, or `None` if `value` is `None`.
    """
    if value is None:
        return None
    if isinstance(value, str):
        value = datetime.fromisoformat(value)
    return value.strftime("%d %B %Y, %H:%M")