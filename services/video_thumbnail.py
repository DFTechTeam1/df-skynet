import os
import tempfile
import time
from pathlib import Path
from typing import Optional
from httpx import Timeout, stream
from apps.secret import UDIN_API_KEY
from log import logging
from utils import get_project_root
from utils.formatter import format_udin_url

THUMBNAIL_DIR = str(get_project_root() / "storages" / "thumbnail")
LONG_SIDE = 480
FRAME_SECOND = 5  # for videos longer than this
SHORT_FRAME_SECOND = 1  # for the rest: a 5s video has no frame at second 5
DOWNLOAD_DEADLINE = 20
DOWNLOAD_TIMEOUT = Timeout(connect=5, read=10, write=10, pool=5)


def _download(url: str, target: str) -> None:
    deadline = time.monotonic() + DOWNLOAD_DEADLINE
    with stream("GET", url, headers={"X-API-Key": UDIN_API_KEY}, timeout=DOWNLOAD_TIMEOUT) as response:
        response.raise_for_status()
        with open(target, "wb") as file:
            for chunk in response.iter_bytes():
                if time.monotonic() > deadline:
                    raise TimeoutError("video download for thumbnail exceeded the deadline")
                file.write(chunk)


def _read_frame(video: str):
    """The frame at `FRAME_SECOND`, or at `SHORT_FRAME_SECOND` when the video isn't longer than that. Falls back to
    second 0 when that frame can't be read."""
    import cv2

    capture = cv2.VideoCapture(video)
    try:
        fps = capture.get(cv2.CAP_PROP_FPS)
        duration = capture.get(cv2.CAP_PROP_FRAME_COUNT) / fps if fps > 0 else 0
        second = FRAME_SECOND if duration > FRAME_SECOND else SHORT_FRAME_SECOND
        capture.set(cv2.CAP_PROP_POS_MSEC, second * 1000)
        ok, frame = capture.read()
    finally:
        capture.release()
    if not ok:
        capture = cv2.VideoCapture(video)  # reopened: a failed seek leaves the capture at an unknown position
        try:
            ok, frame = capture.read()
        finally:
            capture.release()
    if not ok:
        raise ValueError("no frame could be read from the video")
    return frame


def _frame_webp(video: str) -> bytes:
    import cv2

    frame = _read_frame(video)
    height, width = frame.shape[:2]
    scale = LONG_SIDE / max(height, width)
    if scale < 1:
        size = (max(1, round(width * scale)), max(1, round(height * scale)))
        frame = cv2.resize(frame, size, interpolation=cv2.INTER_AREA)
    ok, encoded = cv2.imencode(".webp", frame, [cv2.IMWRITE_WEBP_QUALITY, 80])
    if not ok:
        raise ValueError("webp encoding failed")
    return encoded.tobytes()


def create(storage_path: str, uid: str) -> Optional[str]:
    """Thumbnail of one frame (see `_read_frame`) of the video at udin `storage_path`. Returns the filename to store in the
    `thumbnail` column, or None on any failure: a missing thumbnail must never fail the video itself."""
    try:
        os.makedirs(THUMBNAIL_DIR, exist_ok=True)
        with tempfile.TemporaryDirectory() as workdir:
            video = os.path.join(workdir, "video" + Path(storage_path).suffix)
            _download(format_udin_url(storage_path), video)
            content = _frame_webp(video)
        filename = f"{uid}.webp"
        target = Path(THUMBNAIL_DIR) / filename
        tmp = target.with_suffix(f".{os.getpid()}.tmp")
        tmp.write_bytes(content)
        os.replace(tmp, target)
        return filename
    except Exception:
        logging.exception(f"video thumbnail failed uid={uid}")
        return None


def remove(filename: Optional[str]) -> None:
    """Deletes a thumbnail file. Never raises."""
    if not filename:
        return
    try:
        (Path(THUMBNAIL_DIR) / filename).unlink(missing_ok=True)
    except OSError:
        logging.exception(f"failed to remove thumbnail {filename}")
