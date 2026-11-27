from typing import Any, Literal
from sqlalchemy import or_, update
from log import logging
from services import video_thumbnail
from services.celery_app import celery_app
from services.mysql import get_sync_db
from services.mysql.model import DfEngineGenerationResults, DfEngineGenerations, DfEngineUploadFiles
from services.redis import CacheKeys, delete_pattern_sync, invalidate_project_files_sync, sync_client
from services.tasks.base import retry_countdown
from services.tasks.search_sync import search_upsert

ThumbnailKind = Literal["generation", "upload"]


@celery_app.task(
    bind=True,
    name="df_engine.video_thumbnail",
    retry_backoff=True,
    retry_backoff_max=60,
    retry_jitter=True,
    max_retries=3,
    soft_time_limit=90,
    time_limit=120,
)
def generate_video_thumbnail(self, kind: ThumbnailKind, uid: str) -> dict[str, Any]:
    """Create the thumbnail of one video (`generation` -> results row, `upload` -> upload file row) and drop every
    cache that already holds the row without it. Safe to repeat."""
    model: Any = DfEngineGenerationResults if kind == "generation" else DfEngineUploadFiles
    with get_sync_db() as db:
        row = db.query(model).filter(model.uid == uid).first()
        if row is None or row.thumbnail:
            return {"uid": uid, "status": "skipped"}
        path = row.path

    filename = video_thumbnail.create(path, uid)  # no DB connection is held while downloading
    if filename is None:
        if self.request.retries >= self.max_retries:
            logging.error(f"video thumbnail gave up kind={kind} uid={uid}")
            return {"uid": uid, "status": "failed"}
        raise self.retry(countdown=retry_countdown(self))

    with get_sync_db() as db:
        row = db.query(model).filter(model.uid == uid).first()
        if row is None:  # deleted while the thumbnail was being made
            video_thumbnail.remove(filename)
            return {"uid": uid, "status": "skipped"}
        # updated_at is written back as-is: a thumbnail is not an edit, and results have `onupdate`
        db.execute(update(model).where(model.id == row.id).values(thumbnail=filename, updated_at=row.updated_at))
        _invalidate_caches(db, kind, row)

    search_upsert.delay(kind, uid)  # type: ignore
    return {"uid": uid, "status": "success"}


def _invalidate_caches(db: Any, kind: ThumbnailKind, row: Any) -> None:
    db.commit()  # the new value must be visible before anything can repopulate a cache
    redis, key = sync_client(), CacheKeys()
    if kind == "upload":
        project_id, task_id, song_id = row.project_id, row.task_id, row.song_id
        redis.delete(key.user_file_detail(row.uid))
        delete_pattern_sync(redis, key.user_files_pattern(task_id=task_id, song_id=song_id))
    else:
        generation = db.get(DfEngineGenerations, row.generation_id)
        project_id, task_id, song_id = generation.project_id, generation.task_id, generation.song_id
        delete_pattern_sync(redis, key.generation_files_main_list_pattern(task_id or song_id))
        # the detail of every version of the family embeds its sibling versions
        root = row.parent_id or row.id
        family = db.query(DfEngineGenerationResults.uid).filter(
            or_(DfEngineGenerationResults.id == root, DfEngineGenerationResults.parent_id == root)  # type: ignore
        )
        for (family_uid,) in family.all():
            redis.delete(key.generation_files_main_detail(family_uid))
            redis.delete(key.generation_files_variant_detail(family_uid))
            redis.delete(key.generation_files_variants_detail(family_uid))
    invalidate_project_files_sync(redis, key, project_id)
    if row.created_by is not None:
        delete_pattern_sync(redis, key.generation_files_references_picker_pattern(row.created_by))
        for pattern in key.generation_files_user_lists_patterns(row.created_by):
            delete_pattern_sync(redis, pattern)
