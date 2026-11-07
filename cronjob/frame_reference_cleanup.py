import sys
import time
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[1]))
from log import logging
from services.frame_reference_color import FRAME_COLOR_DIR, in_use, remove
from services.mysql import get_sync_db

GRACE_SECONDS = 600


def cleanup() -> int:
    removed = 0
    with get_sync_db() as db:
        for file in Path(FRAME_COLOR_DIR).glob("*.jpg"):
            color, _, ratio = file.stem.partition("_")  # "#fb542b_21:9"
            if time.time() - file.stat().st_mtime < GRACE_SECONDS or in_use(db, color, ratio):
                continue
            removed += remove(color, ratio)
    logging.info(f"frame reference cleanup removed={removed}")
    return removed


if __name__ == "__main__":
    cleanup()
