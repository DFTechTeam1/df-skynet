from functools import lru_cache
from typing import Optional
from pusher import Pusher
from apps.secret import PUSHER_APP_CLUSTER, PUSHER_APP_ID, PUSHER_APP_KEY, PUSHER_APP_SECRET
from log import logging


@lru_cache
def get_pusher() -> Pusher:
    return Pusher(
        app_id=PUSHER_APP_ID,
        key=PUSHER_APP_KEY,
        secret=PUSHER_APP_SECRET,
        cluster=PUSHER_APP_CLUSTER,
        ssl=True,
    )


def broadcast_generation_status(
    project_uid: str, task_uid: str, user_uid: str, gid: str, status: str, error: Optional[str] = None
) -> None:
    try:
        get_pusher().trigger(
            f"private-user-generation-project-{project_uid}-task-{task_uid}-user-{user_uid}",
            "generation-status",
            {"s": status, "e": error, "gid": gid},
        )
    except Exception:
        logging.exception(f"pusher broadcast failed user_uid={user_uid} gid={gid} status={status}")
