import shutil

import cv2
import numpy as np
import pytest

from parser.openrouter import parse_openrouter_payload
from services import video_thumbnail


@pytest.fixture
def thumbnail_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(video_thumbnail, "THUMBNAIL_DIR", str(tmp_path / "thumbnail"))
    return tmp_path / "thumbnail"


def test_create_writes_a_downscaled_webp(tmp_path, thumbnail_dir, monkeypatch):
    source = str(tmp_path / "source.mp4")
    writer = cv2.VideoWriter(source, cv2.VideoWriter_fourcc(*"mp4v"), 5, (1280, 720))
    writer.write(np.full((720, 1280, 3), 128, dtype=np.uint8))
    writer.release()
    monkeypatch.setattr(video_thumbnail, "_download", lambda url, target: shutil.copy(source, target))

    assert video_thumbnail.create("storage/p/upload/videos/a.mp4", "abc") == "abc.webp"
    assert cv2.imread(str(thumbnail_dir / "abc.webp")).shape[:2] == (270, 480)

    video_thumbnail.remove("abc.webp")
    video_thumbnail.remove("abc.webp")  # already gone: still no error
    assert not (thumbnail_dir / "abc.webp").exists()


@pytest.mark.parametrize(
    "seconds, expected_second",
    [(8, 5), (5, 1), (3, 1), (0.6, 0)],  # longer than 5s, exactly 5s, short, too short even for second 1
)
def test_frame_is_taken_at_second_5_then_1_then_0(tmp_path, seconds, expected_second):
    source = str(tmp_path / "source.mp4")
    fps = 10
    writer = cv2.VideoWriter(source, cv2.VideoWriter_fourcc(*"mp4v"), fps, (320, 240))
    for index in range(int(fps * seconds)):  # each second has its own brightness
        writer.write(np.full((240, 320, 3), index // fps * 30 + 10, dtype=np.uint8))
    writer.release()

    frame = video_thumbnail._read_frame(source)

    assert round((frame.mean() - 10) / 30) == expected_second


def test_create_returns_none_for_an_unreadable_video(thumbnail_dir, monkeypatch):
    monkeypatch.setattr(video_thumbnail, "_download", lambda url, target: open(target, "wb").write(b"not a video"))

    assert video_thumbnail.create("storage/p/upload/videos/a.mp4", "abc") is None
    assert not (thumbnail_dir / "abc.webp").exists()


def test_payload_sends_video_references_as_video_url():
    payload = parse_openrouter_payload("m", "p", {}, ["i.png", "v.mp4"], "video", video_urls={"v.mp4"})

    assert payload["input_references"] == [
        {"type": "image_url", "image_url": {"url": "i.png"}},
        {"type": "video_url", "video_url": {"url": "v.mp4"}},
    ]
