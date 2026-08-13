from datetime import datetime
from pathlib import Path
from pytz import timezone


def get_project_root() -> Path:
    """Resolve project root path."""
    return Path(__file__).resolve().parents[1]


def local_time() -> datetime:
    """Resolve current datetime in WIB"""
    return datetime.now(timezone("Asia/Jakarta")).replace(tzinfo=None)
