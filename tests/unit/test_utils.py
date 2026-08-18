from datetime import datetime, timedelta
from pytz import timezone
from utils import get_project_root, local_time


def test_get_project_root_resolves_repo_root():
    """Resolved root path contains pyproject.toml and the utils directory."""
    root = get_project_root()
    assert (root / "pyproject.toml").exists()
    assert (root / "utils").is_dir()


def test_local_time_is_naive_and_close_to_now_in_wib():
    """Returned datetime is timezone-naive and within 5 seconds of current WIB time."""
    result = local_time()
    assert result.tzinfo is None
    expected = datetime.now(timezone("Asia/Jakarta")).replace(tzinfo=None)
    assert abs(result - expected) < timedelta(seconds=5)
