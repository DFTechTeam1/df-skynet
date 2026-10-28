from typing import Any, Literal
from celery.signals import worker_ready
from sqlalchemy import or_, update
from log import logging
from services.celery_app import celery_app
from services.mysql import get_sync_db
from services.mysql.model import DfEngineGenerationResults, DfEngineGenerations, DfEngineUploadFiles
from services.mysql.model.df_engine_generations import GenerationStatuses
from services.mysql.model.df_engine_upload_files import UploadFileTypes
from services.search import get_search_engine
from services.search.docs import (
    FILTER_FIELDS,
    GENERATION_KINDS,
    MAIN_GENERATIONS,
    SEARCHABLE_FIELDS,
    UPLOADED_FILES,
    build_generation_doc,
    build_upload_doc,
    generation_load_options,
    generation_qualifies,
    upload_load_options,
    upload_qualifies,
)
from services.tasks.base import retry_countdown
from utils import local_time

BACKFILL_BATCH = 500
SyncKind = Literal["generation", "upload"]
_RETRY = dict(retry_backoff=True, retry_backoff_max=60, retry_jitter=True, max_retries=5)


@worker_ready.connect
def ensure_index_settings(**_: Any) -> None:
    """Apply the searchable/filterable fields to both indexes whenever a worker starts, so a new Algolia app or
    environment works without dashboard setup. Never blocks startup: a failure is logged and the next start retries."""
    try:
        for index in (MAIN_GENERATIONS, UPLOADED_FILES):
            get_search_engine().configure_index(index, SEARCHABLE_FIELDS, FILTER_FIELDS)
    except Exception:
        logging.exception("search index settings could not be applied")


@celery_app.task(bind=True, name="df_engine.search_upsert", **_RETRY)
def search_upsert(self, kind: SyncKind, uid: str) -> dict[str, Any]:
    """Make the index agree with the DB for one file: index it when it qualifies, otherwise remove it. Safe to repeat,
    so it covers create, rename, move and "stopped being main" alike. `indexed_at` is set only after Algolia accepted
    the document, and cleared when the document is removed."""
    generation = kind == "generation"
    model: Any = DfEngineGenerationResults if generation else DfEngineUploadFiles
    index = MAIN_GENERATIONS if generation else UPLOADED_FILES
    try:
        with get_sync_db() as db:
            row = (
                db.query(model)
                .options(*(generation_load_options() if generation else upload_load_options()))
                .filter(model.uid == uid)
                .first()
            )
            if row is None:
                get_search_engine().delete(index, [uid])
                return {"uid": uid, "index": index, "action": "deleted"}

            if generation_qualifies(row) if generation else upload_qualifies(row):
                get_search_engine().upsert(index, [build_generation_doc(row) if generation else build_upload_doc(row)])
                indexed_at, action = local_time(), "upserted"
            else:
                get_search_engine().delete(index, [uid])
                indexed_at, action = None, "deleted"
            # updated_at is written back as-is: results have `onupdate`, so leaving it out would bump it and the row
            # would look out of date to the backfill forever.
            db.execute(update(model).where(model.id == row.id).values(indexed_at=indexed_at, updated_at=row.updated_at))
            return {"uid": uid, "index": index, "action": action}
    except Exception as exc:
        if self.request.retries >= self.max_retries:
            logging.exception(f"search_upsert gave up kind={kind} uid={uid}")
            raise
        raise self.retry(exc=exc, countdown=retry_countdown(self))


@celery_app.task(bind=True, name="df_engine.search_delete", **_RETRY)
def search_delete(self, index: str, uids: list[str]) -> dict[str, Any]:
    """Remove documents of rows that no longer exist (the DB row is gone, so there is nothing to reload)."""
    try:
        get_search_engine().delete(index, uids)
    except Exception as exc:
        if self.request.retries >= self.max_retries:
            logging.exception(f"search_delete gave up index={index} count={len(uids)}")
            raise
        raise self.retry(exc=exc, countdown=retry_countdown(self))
    return {"index": index, "deleted": len(uids)}


def _not_indexed(model: Any) -> Any:
    return or_(model.indexed_at.is_(None), model.indexed_at < model.updated_at)


@celery_app.task(name="df_engine.search_backfill")
def search_backfill() -> dict[str, int]:
    """Queue `search_upsert` for every qualifying row that was never indexed or changed since. Re-runnable."""
    with get_sync_db() as db:
        generation_uids = [
            uid
            for (uid,) in db.query(DfEngineGenerationResults.uid)
            .join(DfEngineGenerations, DfEngineGenerations.id == DfEngineGenerationResults.generation_id)
            .filter(
                DfEngineGenerationResults.is_main.is_(True),
                DfEngineGenerations.kind.in_(GENERATION_KINDS),
                DfEngineGenerations.status == GenerationStatuses.success,
                _not_indexed(DfEngineGenerationResults),
            )
            .limit(BACKFILL_BATCH)
            .all()
        ]
        upload_uids = [
            uid
            for (uid,) in db.query(DfEngineUploadFiles.uid)
            .filter(
                DfEngineUploadFiles.type.in_((UploadFileTypes.image, UploadFileTypes.video)),
                _not_indexed(DfEngineUploadFiles),
            )
            .limit(BACKFILL_BATCH)
            .all()
        ]
    for uid in generation_uids:
        search_upsert.delay("generation", uid)  # type: ignore
    for uid in upload_uids:
        search_upsert.delay("upload", uid)  # type: ignore
    logging.info(f"search_backfill queued generations={len(generation_uids)} uploads={len(upload_uids)}")
    return {"generations": len(generation_uids), "uploads": len(upload_uids)}
