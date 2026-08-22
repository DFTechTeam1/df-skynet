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
