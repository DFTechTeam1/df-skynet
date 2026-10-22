from typing import Any
from log import logging
from services.celery_app import celery_app
from services.mysql import get_sync_db
from services.mysql.model import DfEngineGenerations, DfEngineGenerationUploads
from services.mysql.model.df_engine_generation_uploads import UploadStatuses
from services.tasks.udin_uploader import MAX_SWEEP_ATTEMPTS, udin_uploader  # noqa: F401


@celery_app.task(name="df_engine.udin_sweep")
def udin_sweep() -> dict[str, Any]:
    with get_sync_db() as db:
        candidates = (
            db.query(DfEngineGenerationUploads.generation_id, DfEngineGenerations.created_by)
            .join(DfEngineGenerations, DfEngineGenerations.id == DfEngineGenerationUploads.generation_id)
            .filter(
                DfEngineGenerationUploads.needs_reconciliation == True,  # noqa: E712
                DfEngineGenerationUploads.upload_status != UploadStatuses.success,
                DfEngineGenerationUploads.sweep_attempts < MAX_SWEEP_ATTEMPTS,
                DfEngineGenerations.created_by.isnot(None),
            )
            .all()
        )

    for generation_id, user_id in candidates:
        udin_uploader.delay(generation_id, user_id)  # type: ignore

    logging.info(f"udin_sweep requeued {len(candidates)} stuck upload(s)")
    return {"requeued": len(candidates)}
