import json
import time
from typing import Any
from celery.exceptions import SoftTimeLimitExceeded
from httpx import HTTPStatusError, NetworkError, Timeout, TimeoutException
from sqlalchemy import or_
from apps.secret import UDIN_API_KEY, UDIN_BASE_URL
from log import logging
from services.api_caller import APICaller
from services.celery_app import celery_app
from services.slack_notifier import notify_udin_upload_failed
from services.dto import SyncedConnectionContext
from services.dto.synced.projects import get_project
from services.mysql import get_sync_db
from services.mysql.model import (
    DfEngineApiKeys,
    DfEngineApiKeySnapshots,
    DfEngineGenerationReconciliationIssues,
    DfEngineGenerationReferences,
    DfEngineGenerationResults,
    DfEngineGenerationUploads,
    DfEngineGenerations,
    ProjectTasks,
    Users,
)
from services.mysql.model.df_engine_generation_uploads import UploadStatuses
from services.mysql.model.df_engine_generations import GenerationKinds, GenerationStatuses
from services.pusher import broadcast_generation_status
from services.redis import (
    CacheKeys,
    delete_pattern_sync,
    invalidate_project_files_sync,
    get_json_sync,
    set_json_sync,
    sync_client,
)
from error import DataNotFoundError
from utils import local_time
from services.tasks.search_sync import search_upsert
from services.tasks.base import (
    GenerationStageError,
    GenerationTask,
    classify_error,
    response_error_message,
    retry_countdown,
)

IMAGE_UPLOAD_TIMEOUT = Timeout(connect=5, read=15, write=15, pool=10)
IMAGE_MEDIA_TYPES = {
    "png": "image/png",
    "jpeg": "image/jpeg",
    "jpg": "image/jpeg",
    "webp": "image/webp",
    "svg": "image/svg+xml",
}
LOCAL_COMMIT_ATTEMPTS = 3
LOCAL_COMMIT_BACKOFF_SECONDS = 1


@celery_app.task(
    bind=True,
    base=GenerationTask,
    name="df_engine.udin_uploader",
    retry_backoff=True,
    retry_backoff_max=20,
    retry_jitter=True,
    max_retries=5,
    soft_time_limit=330,
    time_limit=360,
    rate_limit="10/s",
)
def udin_uploader(
    self,
    generation_id: int,
    user_id: int,
) -> dict[str, Any]:
    with get_sync_db() as db:
        upload = db.query(DfEngineGenerationUploads).filter_by(generation_id=generation_id).first()
        existing_results = (
            db.query(DfEngineGenerationResults)
            .filter_by(generation_id=generation_id)
            .order_by(DfEngineGenerationResults.version)  # type: ignore
            .all()
        )
        if upload is not None and upload.upload_status == UploadStatuses.success:
            return {
                "generation_id": generation_id,
                "status": "success",
                "skipped": True,
                "result_ids": [result.id for result in existing_results],
            }

        generation = db.get(DfEngineGenerations, generation_id)
        if generation is None or not generation.response:
            raise GenerationStageError("df_engine_generations.response not found or empty", source="udin", final=True)
        if generation.project_id is None:
            raise GenerationStageError("df_engine_generations.project_id not set", source="udin", final=True)

        try:
            project = get_project(
                SyncedConnectionContext(db, sync_client(), CacheKeys()), project_id=generation.project_id
            )
        except DataNotFoundError:
            raise GenerationStageError("linked project not found", source="udin", final=True)

        project_uid = project["uid"]
        # OpenRouter jobs are only visible to the key that created them: Udin must poll with the generation's own key
        key_model = (
            DfEngineApiKeys if generation.sourceable_type == DfEngineApiKeys.__name__ else DfEngineApiKeySnapshots
        )
        source_key = db.get(key_model, generation.sourceable_id)
        openrouter_api_key = source_key.key if source_key else None
        generation_uid = str(generation.uid)
        media_type = IMAGE_MEDIA_TYPES.get(
            str((generation.parameter or {}).get("output_format", "png")).lower(), "image/png"
        )
        task_id = generation.task_id
        project_id = generation.project_id
        task_uid = None
        if task_id is not None:
            task_row = db.query(ProjectTasks.uid).filter_by(id=task_id).first()
            task_uid = str(task_row[0]) if task_row else None
        user_row = db.query(Users.uid).filter_by(id=user_id).first()
        user_uid = str(user_row[0]) if user_row else None
        images = [] if generation.kind == GenerationKinds.video else list(json.loads(generation.response).values())
        job = json.loads(generation.response) if generation.kind == GenerationKinds.video else None
        uploaded_versions = {result.version for result in existing_results}
        parent = next((result for result in existing_results if result.parent_id is None), None)
        parent_id = parent.id if parent else None
        version_start = 0
        family_ids: list[int] = []

        if generation.kind == GenerationKinds.image_edit:
            reference = (
                db.query(DfEngineGenerationReferences)
                .filter_by(generation_id=generation_id)
                .order_by(DfEngineGenerationReferences.id)  # type: ignore
                .first()
            )
            source_result = db.get(DfEngineGenerationResults, reference.result_id) if reference else None
            if source_result is not None:
                root_id = source_result.parent_id or source_result.id
                family = (
                    db.query(DfEngineGenerationResults)
                    .filter(
                        or_(
                            DfEngineGenerationResults.id == root_id,  # type: ignore
                            DfEngineGenerationResults.parent_id == root_id,  # type: ignore
                        )
                    )
                    .all()
                )
                family_ids = [result.id for result in family]
                version_start = max((result.version for result in family), default=0)
                parent_id = root_id

    # Udin replies only after it has fetched/saved/hashed the file (videos are downloaded from OpenRouter
    # first), so the read timeout must stay below soft_time_limit but well above 120s.
    caller = APICaller(
        base_url=UDIN_BASE_URL,
        headers={"X-API-Key": UDIN_API_KEY},
        timeout=Timeout(connect=10, read=300, write=60, pool=10),  # type: ignore[arg-type]
    )
    demoted_family = False
    try:
        if generation.kind == GenerationKinds.video:
            if 1 not in uploaded_versions:
                if not openrouter_api_key:
                    raise GenerationStageError("generation api key not found", source="udin", final=True)
                try:
                    response = caller.udin_sync(
                        "POST",
                        f"/engine/storage/upload-generated-video/{project_uid}",
                        user_id=user_id,
                        params={"project_name": project["name"]},
                        json={"polling_url": job["polling_url"], "openrouter_api_key": openrouter_api_key},  # type: ignore
                    )
                except (TimeoutException, NetworkError, SoftTimeLimitExceeded) as exc:
                    stage_error = classify_error(exc, source="udin")
                    can_retry = stage_error.retryable and self.request.retries < self.max_retries
                    _bump_sweep_attempts(generation_id, final=not can_retry, detail=str(stage_error))
                    if can_retry:
                        raise self.retry(exc=stage_error, countdown=retry_countdown(self))
                    raise stage_error

                if response.is_error:
                    stage_error = classify_error(
                        HTTPStatusError(response_error_message(response), request=response.request, response=response),
                        source="udin",
                    )
                    can_retry = stage_error.retryable and self.request.retries < self.max_retries
                    _bump_sweep_attempts(generation_id, final=not can_retry, detail=str(stage_error))
                    if can_retry:
                        raise self.retry(exc=stage_error, countdown=retry_countdown(self))
                    raise stage_error

                uploaded = response.json().get("data") or {}
                with get_sync_db() as db:
                    db.add(
                        DfEngineGenerationResults(
                            generation_id=generation_id,
                            name=uploaded.get("name", ""),
                            path=uploaded.get("path", ""),
                            size=uploaded.get("size", 0),
                            md5=uploaded.get("md5"),
                            version=1,
                            is_main=True,
                            parent_id=None,
                            created_by=user_id,
                        )
                    )
                    db.flush()
        else:
            for idx, b64_json in enumerate(images):
                version = version_start + idx + 1
                if version in uploaded_versions:
                    continue

                try:
                    response = caller.udin_sync(
                        "POST",
                        f"/engine/storage/upload-generated-image/{project_uid}",
                        user_id=user_id,
                        params={"project_name": project["name"]},
                        json={"b64_json": b64_json, "media_type": media_type},
                        timeout=IMAGE_UPLOAD_TIMEOUT,
                    )
                except (TimeoutException, NetworkError, SoftTimeLimitExceeded) as exc:
                    stage_error = classify_error(exc, source="udin")
                    can_retry = stage_error.retryable and self.request.retries < self.max_retries
                    _bump_sweep_attempts(generation_id, final=not can_retry, detail=str(stage_error))
                    if can_retry:
                        raise self.retry(exc=stage_error, countdown=retry_countdown(self))
                    raise stage_error

                if response.is_error:
                    stage_error = classify_error(
                        HTTPStatusError(response_error_message(response), request=response.request, response=response),
                        source="udin",
                    )
                    can_retry = stage_error.retryable and self.request.retries < self.max_retries
                    _bump_sweep_attempts(generation_id, final=not can_retry, detail=str(stage_error))
                    if can_retry:
                        raise self.retry(exc=stage_error, countdown=retry_countdown(self))
                    raise stage_error

                uploaded = response.json().get("data") or {}
                with get_sync_db() as db:
                    if family_ids and not demoted_family:
                        db.query(DfEngineGenerationResults).filter(
                            DfEngineGenerationResults.id.in_(family_ids)  # type: ignore
                        ).update({DfEngineGenerationResults.is_main: False}, synchronize_session=False)  # type: ignore
                        demoted_family = True

                    result = DfEngineGenerationResults(
                        generation_id=generation_id,
                        name=uploaded.get("name", ""),
                        path=uploaded.get("path", ""),
                        size=uploaded.get("size", 0),
                        md5=uploaded.get("md5"),
                        version=version,
                        is_main=idx == len(images) - 1,
                        parent_id=parent_id,
                        created_by=user_id,
                    )
                    db.add(result)
                    db.flush()
                    db.refresh(result)
                    if not family_ids and idx == 0:
                        parent_id = result.id
    finally:
        caller.sync_client.close()

    with get_sync_db() as db:
        saved = db.query(DfEngineGenerationResults).filter_by(generation_id=generation_id).all()
    if not saved or any(not result.path for result in saved):
        _bump_sweep_attempts(generation_id, final=True, detail="no stored file for generation")
        raise GenerationStageError("no stored file returned for generation", source="udin", final=True)

    for attempt in range(1, LOCAL_COMMIT_ATTEMPTS + 1):
        try:
            with get_sync_db() as db:
                upload = db.query(DfEngineGenerationUploads).filter_by(generation_id=generation_id).first()
                if upload is None:
                    upload = DfEngineGenerationUploads(generation_id=generation_id)
                upload.upload_status = UploadStatuses.success
                upload.uploaded_at = local_time()
                if upload.needs_reconciliation:
                    upload.needs_reconciliation = False
                    upload.reconciled_at = local_time()
                    db.query(DfEngineGenerationReconciliationIssues).filter(
                        DfEngineGenerationReconciliationIssues.generation_id == generation_id,  # type: ignore
                        DfEngineGenerationReconciliationIssues.resolved_at.is_(None),  # type: ignore
                    ).update(
                        {DfEngineGenerationReconciliationIssues.resolved_at: local_time()},
                        synchronize_session=False,  # type: ignore
                    )
                db.add(upload)

                generation = db.get(DfEngineGenerations, generation_id)
                generation.status = GenerationStatuses.success  # type: ignore
                db.add(generation)

                results = (
                    db.query(DfEngineGenerationResults)
                    .filter_by(generation_id=generation_id)
                    .order_by(DfEngineGenerationResults.version)  # type: ignore
                    .all()
                )
                result_ids = [result.id for result in results]
                result_uids = [result.uid for result in results]

            redis = sync_client()
            cache_key = CacheKeys()
            generation_detail_key = cache_key.generation_detail(user_id, generation_uid)
            cached_generation_detail = get_json_sync(redis, generation_detail_key)
            if cached_generation_detail is not None:
                set_json_sync(redis, generation_detail_key, {**cached_generation_detail, "status": generation.status})  # type: ignore
            invalidate_project_files_sync(redis, cache_key, project_id)
            if task_id is not None:
                delete_pattern_sync(redis, cache_key.user_files_pattern(task_id=task_id))
                delete_pattern_sync(redis, cache_key.generation_files_main_list_pattern(task_id))
                for pattern in cache_key.generation_files_user_lists_patterns(user_id):
                    delete_pattern_sync(redis, pattern)

            if family_ids:
                with get_sync_db() as db:
                    family_rows = (
                        db.query(DfEngineGenerationResults.uid, DfEngineGenerations.task_id)  # type: ignore
                        .join(DfEngineGenerations, DfEngineGenerations.id == DfEngineGenerationResults.generation_id)
                        .filter(DfEngineGenerationResults.id.in_(family_ids))  # type: ignore
                        .all()
                    )
                for family_uid, family_task_id in family_rows:
                    search_upsert.delay("generation", family_uid)  # type: ignore  # demoted main leaves the index
                    redis.delete(cache_key.generation_files_main_detail(family_uid))
                    redis.delete(cache_key.generation_files_variant_detail(family_uid))
                    redis.delete(cache_key.generation_files_variants_detail(family_uid))
                    if family_task_id is not None:
                        delete_pattern_sync(redis, cache_key.generation_files_main_list_pattern(family_task_id))

            for result_uid in result_uids:
                search_upsert.delay("generation", result_uid)  # type: ignore

            if task_uid is not None and user_uid is not None:
                broadcast_generation_status(project_uid, task_uid, user_uid, generation_uid, "success")
            return {"generation_id": generation_id, "status": "success", "result_ids": result_ids}
        except Exception:
            logging.exception(f"udin_uploader local commit failed attempt={attempt} generation_id={generation_id}")
            if attempt < LOCAL_COMMIT_ATTEMPTS:
                time.sleep(LOCAL_COMMIT_BACKOFF_SECONDS)

    _bump_sweep_attempts(
        generation_id, final=True, detail=f"local commit failed after {LOCAL_COMMIT_ATTEMPTS} attempts"
    )
    raise GenerationStageError(
        f"local commit failed after {LOCAL_COMMIT_ATTEMPTS} attempts, upload already succeeded on Udin",
        source="udin",
        final=True,
    )


MAX_SWEEP_ATTEMPTS = 12  # one failed run = 6 attempts, so the sweep re-uploads once; then `failed` -> manual re-upload


def _bump_sweep_attempts(generation_id: int, final: bool = False, detail: str = "") -> None:
    with get_sync_db() as db:
        upload = db.query(DfEngineGenerationUploads).filter_by(generation_id=generation_id).first()
        if upload is None:
            upload = DfEngineGenerationUploads(generation_id=generation_id)
        upload.sweep_attempts += 1
        newly_flagged = final and not upload.needs_reconciliation
        newly_failed = False
        if final:
            upload.needs_reconciliation = True
            if upload.sweep_attempts >= MAX_SWEEP_ATTEMPTS:
                newly_failed = upload.upload_status != UploadStatuses.failed
                upload.upload_status = UploadStatuses.failed  # auto-retry exhausted: only a manual re-upload is left
        db.add(upload)
        db.flush()
        if newly_flagged:
            db.add(
                DfEngineGenerationReconciliationIssues(
                    generation_id=generation_id,
                    upload_id=upload.id,
                    issue_type="udin_upload_failed",
                    detail=detail[:2000],
                )
            )

    if newly_failed:
        generation_uid, project_name = str(generation_id), "-"
        try:
            with get_sync_db() as db:
                generation = db.get(DfEngineGenerations, generation_id)
                if generation is not None:
                    generation_uid = str(generation.uid)
                    if generation.project_id is not None:
                        project_name = get_project(
                            SyncedConnectionContext(db, sync_client(), CacheKeys()), project_id=generation.project_id
                        )["name"]
        except Exception:
            logging.exception(f"slack notify lookup failed generation_id={generation_id}")
        notify_udin_upload_failed(generation_uid, project_name, detail)
