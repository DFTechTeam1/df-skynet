"""Solid-color frame reference images for video generations (`default_frame_reference_color`).

Files are shared by (color, aspect_ratio): created once, reused by later requests, and deleted by the
generation worker once no active generation still needs them. `cronjob/frame_reference_cleanup.py` is the backup."""

import os
from pathlib import Path
from urllib.parse import quote

from PIL import Image

from apps.secret import BASE_URL
from log import logging
from utils import get_project_root

FRAME_COLOR_DIR = str(get_project_root() / "storages" / "frame_reference_colors")
FRAME_COLOR_URL_PATH = "storages/frame_reference_colors"
LONG_SIDE = 1280


def _filename(color: str, aspect_ratio: str) -> str:
    return f"{color}_{aspect_ratio}.jpg"


def _path(color: str, aspect_ratio: str) -> Path:
    return Path(FRAME_COLOR_DIR) / _filename(color, aspect_ratio)


def _size(aspect_ratio: str) -> tuple[int, int]:
    w, h = (int(x) for x in aspect_ratio.split(":"))
    if w <= 0 or h <= 0:
        raise ValueError(f"invalid aspect ratio {aspect_ratio}")
    return (LONG_SIDE, max(1, round(LONG_SIDE * h / w))) if w >= h else (max(1, round(LONG_SIDE * w / h)), LONG_SIDE)


def create(color: str, aspect_ratio: str) -> str:
    """Returns the public url of the color image, generating the file only when it does not exist yet."""
    path = _path(color, aspect_ratio)
    if not path.exists():
        os.makedirs(FRAME_COLOR_DIR, exist_ok=True)
        tmp = path.with_suffix(f".{os.getpid()}.tmp")
        Image.new("RGB", _size(aspect_ratio), color).save(tmp, format="JPEG", quality=95)
        os.replace(tmp, path)
    return f"{BASE_URL.rstrip('/')}/{FRAME_COLOR_URL_PATH}/{quote(_filename(color, aspect_ratio))}"


def remove(color: str, aspect_ratio: str) -> bool:
    """Deletes the file. A missing file counts as success; False means deletion failed (cronjob retries)."""
    try:
        _path(color, aspect_ratio).unlink(missing_ok=True)
        return True
    except OSError:
        logging.exception(f"failed to remove frame reference color {color} {aspect_ratio}")
        return False


def in_use(db, color: str, aspect_ratio: str, exclude_id: int | None = None) -> bool:
    """True while another queued/processing generation still needs the same file."""
    from services.mysql.model.df_engine_generations import DfEngineGenerations, GenerationStatuses

    rows = (
        db.query(DfEngineGenerations.id, DfEngineGenerations.parameter)
        .filter(
            DfEngineGenerations.color_code == color,
            DfEngineGenerations.status.in_([GenerationStatuses.queued, GenerationStatuses.processing]),
        )
        .all()
    )
    return any(i != exclude_id and (p or {}).get("aspect_ratio") == aspect_ratio for i, p in rows)


def cleanup_generation(generation_id: int) -> None:
    """Worker hook: call once a generation reached a terminal status. Never raises."""
    try:
        from services.mysql import get_sync_db
        from services.mysql.model.df_engine_generations import DfEngineGenerations

        with get_sync_db() as db:
            generation = db.get(DfEngineGenerations, generation_id)
            if generation is None or not generation.color_code:
                return
            ratio = (generation.parameter or {}).get("aspect_ratio")
            if ratio and not in_use(db, generation.color_code, ratio, exclude_id=generation_id):
                remove(generation.color_code, ratio)
    except Exception:
        logging.exception(f"frame reference color cleanup failed generation_id={generation_id}")
