from datetime import timedelta
from typing import Any
from sqlalchemy import func, select
from log import logging
from services.celery_app import celery_app
from services.mysql import get_sync_db
from services.mysql.model import DfEngineGenerations, DfEngineQueues
from services.mysql.model.df_engine_generations import GenerationStatuses
from services.mysql.model.df_engine_queues import QueueEventTypes
from services.pusher import broadcast_generation_status
from services.tasks.base import _generation_broadcast_context, _mark_generation_failed, log_queue
from utils import local_time

# Longest legit gap between two queue events is a video poll (30s) or a retry backoff (60s); the longest single task
# is the uploader's 360s hard limit. Anything silent for longer died without running `on_failure` (e.g. OOM kill).
STALE_AFTER = timedelta(minutes=15)


@celery_app.task(name="df_engine.generation_reaper")
def generation_reaper() -> dict[str, Any]:
    """Force-fail generations stuck in queued/processing with no queue event for STALE_AFTER. Never requeues: a
    requeue could bill OpenRouter twice, so the user retries manually from the failed state."""
    cutoff = local_time() - STALE_AFTER
    last_event = (
        select(func.max(DfEngineQueues.created_at))
        .where(DfEngineQueues.generation_id == DfEngineGenerations.id)
        .scalar_subquery()
    )
    with get_sync_db() as db:
        stale = (
            db.query(DfEngineGenerations.id, DfEngineGenerations.created_by)
            .filter(
                DfEngineGenerations.status.in_([GenerationStatuses.queued, GenerationStatuses.processing]),  # type: ignore
                DfEngineGenerations.created_at < cutoff,
                func.coalesce(last_event, DfEngineGenerations.created_at) < cutoff,
            )
            .all()
        )

    for generation_id, user_id in stale:
        _mark_generation_failed(generation_id)
        log_queue(
            generation_id=generation_id,
            queue_name="df_engine.generation_reaper",
            event_type=QueueEventTypes.failed,
            attempt=1,
            task_id="reaper",
            detail={"message": f"no queue activity for {STALE_AFTER}; worker likely killed (OOM)"},
        )
        context = _generation_broadcast_context(generation_id, user_id) if user_id else None
        if context:
            gid, project_uid, task_uid, user_uid = context
            try:
                broadcast_generation_status(
                    project_uid, task_uid, user_uid, gid, "failed", error="generation timed out"
                )
            except Exception:
                logging.exception(f"reaper pusher failed generation_id={generation_id}")

    logging.info(f"generation_reaper failed {len(stale)} stuck generation(s)")
    return {"reaped": len(stale)}
