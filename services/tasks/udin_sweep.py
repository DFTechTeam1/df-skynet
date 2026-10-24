from datetime import timedelta
from typing import Any
from sqlalchemy import exists
from log import logging
from services.celery_app import celery_app
from services.mysql import get_sync_db
from services.redis import CacheKeys, sync_client
from services.mysql.model import DfEngineGenerationResults, DfEngineGenerations, DfEngineGenerationUploads
from services.mysql.model.df_engine_generations import GenerationKinds, GenerationStatuses
from services.mysql.model.df_engine_generation_uploads import UploadStatuses
from services.tasks.udin_uploader import MAX_SWEEP_ATTEMPTS, udin_uploader  # noqa: F401
from utils import local_time

ORPHAN_MIN_AGE = timedelta(minutes=10)  # only spares brand-new generations; the lock below is the real guard
LOCK_TTL = 400  # same as the manual re-upload endpoint: > the uploader's 360s time limit
FILE_KINDS = (GenerationKinds.image, GenerationKinds.image_edit, GenerationKinds.video)


def flag_orphans() -> int:
    """`success` generations that lost their result rows: flag them so the sweep below re-uploads from `response`."""
    with get_sync_db() as db:
        orphans = (
            db.query(DfEngineGenerations.id, DfEngineGenerationUploads)
            .outerjoin(DfEngineGenerationUploads, DfEngineGenerationUploads.generation_id == DfEngineGenerations.id)
            .filter(
                DfEngineGenerations.status == GenerationStatuses.success,
                DfEngineGenerations.kind.in_(FILE_KINDS),  # type: ignore
                DfEngineGenerations.status_code == 200,
                DfEngineGenerations.response.isnot(None),  # type: ignore
                DfEngineGenerations.created_at < local_time() - ORPHAN_MIN_AGE,
                ~exists().where(DfEngineGenerationResults.generation_id == DfEngineGenerations.id),
            )
            .all()
        )
        flagged = 0
        for generation_id, upload in orphans:
            if upload is None:
                upload = DfEngineGenerationUploads(generation_id=generation_id)
            elif upload.upload_status == UploadStatuses.failed or upload.sweep_attempts >= MAX_SWEEP_ATTEMPTS:
                continue  # retries exhausted: manual re-upload only
            upload.upload_status = UploadStatuses.pending  # the uploader skips rows already marked success
            upload.needs_reconciliation = True
            db.add(upload)
            flagged += 1
    return flagged


@celery_app.task(name="df_engine.udin_sweep")
def udin_sweep() -> dict[str, Any]:
    flagged = flag_orphans()
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

    redis, key = sync_client(), CacheKeys()
    requeued = 0
    for generation_id, user_id in candidates:
        # shared with the manual re-upload endpoint and released by GenerationTask on success/failure
        lock = key.generation_reupload_lock(generation_id)
        if not redis.set(lock, "sweep", nx=True, ex=LOCK_TTL):
            continue  # an upload for this generation is already running
        try:
            udin_uploader.delay(generation_id, user_id)  # type: ignore
        except Exception:
            redis.delete(lock)
            raise
        requeued += 1

    logging.info(f"udin_sweep requeued {requeued}/{len(candidates)} stuck upload(s)")
    return {"requeued": requeued, "orphans_flagged": flagged}
