import pytest
from PIL import Image

from services import frame_reference_color as frc


@pytest.fixture(autouse=True)
def tmp_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(frc, "FRAME_COLOR_DIR", str(tmp_path))


def test_create_sizes_and_reuses_file():
    url = frc.create("#fb542b", "21:9")
    assert url.endswith("/storages/frame_reference_colors/%23fb542b_21%3A9.jpg")
    path = frc._path("#fb542b", "21:9")
    assert Image.open(path).size == (1280, 549)
    mtime = path.stat().st_mtime_ns
    frc.create("#fb542b", "21:9")
    assert path.stat().st_mtime_ns == mtime  # reused, not regenerated
    assert Image.open(frc._path("#fb542b", "9:16") if frc.create("#fb542b", "9:16") else None).size == (720, 1280)


def test_remove_is_idempotent():
    frc.create("#000000", "16:9")
    assert frc.remove("#000000", "16:9") and frc.remove("#000000", "16:9")
