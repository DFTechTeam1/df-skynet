from datetime import datetime
from pathlib import Path
from typing import Optional
from pytz import timezone


def get_project_root() -> Path:
    """Resolve project root path."""
    return Path(__file__).resolve().parents[1]


def local_time() -> datetime:
    """Resolve current datetime in WIB"""
    return datetime.now(timezone("Asia/Jakarta")).replace(tzinfo=None)


def wib_to_utc_iso(wib_naive: Optional[datetime]) -> Optional[str]:
    """Convert a naive WIB wall-clock datetime (as returned by `local_time()`) to a UTC isoformat string ending in `Z`."""
    if wib_naive is None:
        return None
    wib = timezone("Asia/Jakarta").localize(wib_naive)
    return wib.astimezone(timezone("UTC")).isoformat().replace("+00:00", "Z")


def epoch_to_wib(value: Optional[int]) -> Optional[datetime]:
    """Convert a Unix epoch (seconds, UTC) — e.g. OpenRouter's `created` field —
    into a naive WIB wall-clock datetime, matching `local_time()`'s convention."""
    if value is None:
        return None
    return datetime.fromtimestamp(value, tz=timezone("UTC")).astimezone(timezone("Asia/Jakarta")).replace(tzinfo=None)
