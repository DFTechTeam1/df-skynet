from functools import lru_cache
from typing import Optional
from pusher import Pusher
from apps.secret import PUSHER_APP_CLUSTER, PUSHER_APP_ID, PUSHER_APP_KEY, PUSHER_APP_SECRET
from log import logging
from services.mysql import get_sync_db
from services.openrouter_credits import get_stored_credits_sync, refresh_credits_sync
from utils.formatter import format_credit_amount


@lru_cache
def get_pusher() -> Pusher:
    return Pusher(
        app_id=PUSHER_APP_ID,
        key=PUSHER_APP_KEY,
        secret=PUSHER_APP_SECRET,
        cluster=PUSHER_APP_CLUSTER,
        ssl=True,
    )


def _remain() -> int | float:
    """Remaining OpenRouter credit (total_credits - total_usage): live fetch, stored row as fallback, else 0."""
    try:
        with get_sync_db() as db:
            credits = None
            try:
                credits = refresh_credits_sync(db)
            except Exception:
                logging.exception("pusher: live openrouter credits fetch failed, using stored")
            credits = credits or get_stored_credits_sync(db) or {}
        return format_credit_amount(credits.get("total_credits", 0) - credits.get("total_usage", 0))
    except Exception:
        logging.exception("pusher: failed to resolve remaining credits")
        return 0


def broadcast_token() -> None:
    try:
        get_pusher().trigger("remaining-token", "token-update", {"remain": _remain()})
    except Exception:
        logging.exception("pusher token broadcast failed")


def broadcast_generation_status(
    project_uid: str, task_uid: str, user_id: int, gid: str, status: str, error: Optional[str] = None
) -> None:
    try:
        get_pusher().trigger(
            f"user-generation-project-{project_uid}-task-{task_uid}",
            "generation-status",
            {"s": status, "e": error, "gid": gid, "u": user_id},
        )
    except Exception:
        logging.exception(f"pusher broadcast failed user_id={user_id} gid={gid} status={status}")
    if status in ("success", "failed"):
        broadcast_token()
