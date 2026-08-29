from datetime import datetime, date
from typing import Optional, Any


def format_user_employees(user: Optional[dict[str, Any]]) -> Optional[dict[str, Any]]:
    if user is None:
        return None
    employees = user.get("employees") or {}
    return {
        "image": user.get("image"),
        "nickname": employees.get("nickname"),
    }


def format_employee_users(employee: Optional[dict[str, Any]]) -> Optional[dict[str, Any]]:
    if employee is None:
        return None
    users = employee.get("users") or {}
    return {
        "image": users.get("image"),
        "nickname": employee.get("nickname"),
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


def format_date(value: Optional[str] = None) -> Optional[date]:
    if value:
        try:
            return date.fromisoformat(str(value)[:10]) if value else None
        except ValueError:
            return None
    return None
