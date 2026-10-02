import json
import time
from typing import Any
from celery.exceptions import SoftTimeLimitExceeded
from httpx import HTTPStatusError, NetworkError, TimeoutException
from sqlalchemy import or_
from apps.secret import UDIN_API_KEY, UDIN_BASE_URL
from log import logging
from services.api_caller import APICaller
from services.celery_app import celery_app
from services.dto import SyncedConnectionContext
from services.dto.synced.projects import get_project
from services.mysql import get_sync_db
from services.mysql.model import (
    DfEngineGenerationReferences,
    DfEngineGenerationResults,
    DfEngineGenerationUploads,
    DfEngineGenerations,
)
from services.mysql.model.df_engine_generation_uploads import UploadStatuses
from services.mysql.model.df_engine_generations import GenerationKinds, GenerationStatuses
from services.pusher import broadcast_generation_status
from services.redis import CacheKeys, delete_pattern_sync, get_json_sync, set_json_sync, sync_client
from error import DataNotFoundError
from utils import local_time
from services.tasks.base import (
    GenerationStageError,
    GenerationTask,
    classify_error,
    response_error_message,
    retry_countdown,
)

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
    soft_time_limit=45,
    time_limit=60,
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
        generation_uid = str(generation.uid)
        task_id = generation.task_id
        project_id = generation.project_id
        images = list(json.loads(generation.response).values())
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

    caller = APICaller(base_url=UDIN_BASE_URL, headers={"X-API-Key": UDIN_API_KEY}, timeout=30)
    demoted_family = False
    try:
        for idx, b64_json in enumerate(images):
            version = version_start + idx + 1
            if version in uploaded_versions:
                continue  # already uploaded on a prior attempt of this task

            try:
                response = caller.udin_sync(
                    "POST",
                    f"/engine/storage/upload-generated-image/{project_uid}",
                    user_id=user_id,
                    json={"b64_json": b64_json, "media_type": "image/png"},
                )
            except (TimeoutException, NetworkError, SoftTimeLimitExceeded) as exc:
                _bump_sweep_attempts(generation_id)
                stage_error = classify_error(exc, source="udin")
                if stage_error.retryable and self.request.retries < self.max_retries:
                    raise self.retry(exc=stage_error, countdown=retry_countdown(self))
                raise stage_error

            if response.is_error:
                _bump_sweep_attempts(generation_id)
                stage_error = classify_error(
                    HTTPStatusError(response_error_message(response), request=response.request, response=response),
                    source="udin",
                )
                if stage_error.retryable and self.request.retries < self.max_retries:
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
                    is_main=idx == 0,
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

    for attempt in range(1, LOCAL_COMMIT_ATTEMPTS + 1):
        try:
            with get_sync_db() as db:
                upload = db.query(DfEngineGenerationUploads).filter_by(generation_id=generation_id).first()
                if upload is None:
                    upload = DfEngineGenerationUploads(generation_id=generation_id)
                upload.upload_status = UploadStatuses.success
                upload.uploaded_at = local_time()
                db.add(upload)

                generation = db.get(DfEngineGenerations, generation_id)
                generation.status = GenerationStatuses.success  # type: ignore
                db.add(generation)

                result_ids = [
                    result.id
                    for result in db.query(DfEngineGenerationResults)
                    .filter_by(generation_id=generation_id)
                    .order_by(DfEngineGenerationResults.version)  # type: ignore
                    .all()
                ]

            redis = sync_client()
            cache_key = CacheKeys()
            generation_detail_key = cache_key.generation_detail(user_id, generation_uid)
            cached_generation_detail = get_json_sync(redis, generation_detail_key)
            if cached_generation_detail is not None:
                set_json_sync(redis, generation_detail_key, {**cached_generation_detail, "status": generation.status})  # type: ignore
            if task_id is not None:
                delete_pattern_sync(redis, cache_key.user_galleries_pattern(user_id))
                delete_pattern_sync(redis, cache_key.references_picker_pattern(user_id))
                delete_pattern_sync(redis, cache_key.global_references_picker_pattern(user_id))
                delete_pattern_sync(redis, cache_key.user_files_pattern(user_id, task_id))
                delete_pattern_sync(redis, cache_key.generation_files_main_list_pattern(task_id))
                redis.delete(cache_key.generation_files_result_list(user_id, project_id))
                delete_pattern_sync(redis, cache_key.generation_files_references_picker_pattern(user_id))

            if family_ids:
                with get_sync_db() as db:
                    family_rows = (
                        db.query(DfEngineGenerationResults.uid, DfEngineGenerations.task_id)  # type: ignore
                        .join(DfEngineGenerations, DfEngineGenerations.id == DfEngineGenerationResults.generation_id)
                        .filter(DfEngineGenerationResults.id.in_(family_ids))  # type: ignore
                        .all()
                    )
                for family_uid, family_task_id in family_rows:
                    redis.delete(cache_key.generation_files_main_detail(family_uid))
                    redis.delete(cache_key.generation_files_variant_detail(family_uid))
                    redis.delete(cache_key.generation_files_variants_detail(family_uid))
                    if family_task_id is not None:
                        delete_pattern_sync(redis, cache_key.generation_files_main_list_pattern(family_task_id))

            if task_id is not None:
                broadcast_generation_status(project_id, task_id, user_id, generation_uid, "success")
            return {"generation_id": generation_id, "status": "success", "result_ids": result_ids}
        except Exception:
            logging.exception(f"udin_uploader local commit failed attempt={attempt} generation_id={generation_id}")
            if attempt < LOCAL_COMMIT_ATTEMPTS:
                time.sleep(LOCAL_COMMIT_BACKOFF_SECONDS)

    raise GenerationStageError(
        f"local commit failed after {LOCAL_COMMIT_ATTEMPTS} attempts, upload already succeeded on Udin",
        source="udin",
        final=True,
    )


def _bump_sweep_attempts(generation_id: int) -> None:
    with get_sync_db() as db:
        upload = db.query(DfEngineGenerationUploads).filter_by(generation_id=generation_id).first()
        if upload is None:
            upload = DfEngineGenerationUploads(generation_id=generation_id)
        upload.sweep_attempts += 1
        db.add(upload)
