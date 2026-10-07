from datetime import datetime, date
from decimal import Decimal
from typing import Optional, Any
from urllib.parse import quote
from apps.secret import UDIN_BASE_URL


def format_udin_url(path: str) -> str:
    """Build the udin-streamed URL for a stored path, percent-encoding spaces etc. (keeps `/` unescaped)."""
    return f"{UDIN_BASE_URL}/{quote(path, safe='/')}"


def format_user_employees(user: Optional[dict[str, Any]]) -> Optional[dict[str, Any]]:
    if user is None:
        return None
    employees = user.get("employees") or {}
    return {
        "user_id": user.get("id"),
        "image": user.get("image"),
        "nickname": employees.get("nickname"),
    }


def format_employee_users(employee: Optional[dict[str, Any]]) -> Optional[dict[str, Any]]:
    if employee is None:
        return None
    users = employee.get("users") or {}
    return {
        "user_id": employee.get("user_id"),
        "image": users.get("image"),
        "nickname": employee.get("nickname"),
    }


def format_size(size: int) -> str:
    value = float(size)
    if value < 1024:
        return f"{value:.0f} B"
    for unit in ("KB", "MB", "GB"):
        value /= 1024
        if value < 1024 or unit == "GB":
            return f"{value:.2f} {unit}"
    return f"{value:.2f} GB"


def format_idr(usd_cost: Optional[Decimal | float], rate: Decimal | float) -> Optional[str]:
    """Convert a USD cost to a dot-grouped IDR display string (e.g. 'Rp 24.000')."""
    if usd_cost is None:
        return None
    rupiah = round(Decimal(str(usd_cost)) * Decimal(str(rate)))
    return f"Rp {rupiah:,}".replace(",", ".")


def per_image_cost(cost: Optional[Decimal | float], parameter: Optional[dict]) -> Optional[Decimal | float]:
    """A generation's `cost` is billed for the whole batch (`parameter["n"]`
    images) — divide it down to a per-image cost for display."""
    n = (parameter or {}).get("n") or 1
    return cost / n if cost is not None and n > 1 else cost


def format_usd(cost: Optional[Decimal | float]) -> Optional[str]:
    """Format a USD cost as fixed-point (e.g. '$ 0.0000002'), never scientific notation."""
    if cost is None:
        return None
    text = f"{float(cost):.4f}"
    return f"$ {text}"


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
