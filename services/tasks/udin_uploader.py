import time
from typing import Any
from celery.exceptions import SoftTimeLimitExceeded
from httpx import HTTPStatusError, NetworkError, TimeoutException
from apps.secret import UDIN_API_KEY, UDIN_BASE_URL
from log import logging
from services.api_caller import APICaller
from services.celery_app import celery_app
from services.mysql import get_sync_db
from services.mysql.model import DfEngineGenerationResults, DfEngineGenerationUploads, DfEngineGenerations, Projects
from services.mysql.model.df_engine_generation_uploads import UploadStatuses
from services.mysql.model.df_engine_generations import GenerationStatuses
from services.redis import CacheKeys, delete_pattern_sync, sync_client
from services.tasks.base import (
    GenerationStageError,
    GenerationTask,
    classify_error,
    response_error_message,
    retry_countdown,
)
from utils import local_time

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
        if upload is not None and upload.upload_status == UploadStatuses.success:
            result = db.query(DfEngineGenerationResults).filter_by(generation_id=generation_id).first()
            return {
                "generation_id": generation_id,
                "status": "success",
                "skipped": True,
                "result_id": result.id if result else None,
            }

        generation = db.get(DfEngineGenerations, generation_id)
        if generation is None or not generation.response:
            raise GenerationStageError("df_engine_generations.response not found or empty", source="udin", final=True)
        if generation.project_id is None:
            raise GenerationStageError("df_engine_generations.project_id not set", source="udin", final=True)

        project = db.get(Projects, generation.project_id)
        if project is None:
            raise GenerationStageError("linked project not found", source="udin", final=True)

        project_uid = project.uid
        task_id = generation.task_id

    caller = APICaller(base_url=UDIN_BASE_URL, headers={"X-API-Key": UDIN_API_KEY}, timeout=30)
    try:
        response = caller.udin_sync(
            "POST",
            f"/engine/storage/upload-generated-image/{project_uid}",
            user_id=user_id,
            json={"b64_json": generation.response, "media_type": "image/png"},
        )
    except (TimeoutException, NetworkError, SoftTimeLimitExceeded) as exc:
        _bump_sweep_attempts(generation_id)
        stage_error = classify_error(exc, source="udin")
        if stage_error.retryable and self.request.retries < self.max_retries:
            raise self.retry(exc=stage_error, countdown=retry_countdown(self))
        raise stage_error
    finally:
        caller.sync_client.close()

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

    for attempt in range(1, LOCAL_COMMIT_ATTEMPTS + 1):
        try:
            with get_sync_db() as db:
                upload = db.query(DfEngineGenerationUploads).filter_by(generation_id=generation_id).first()
                if upload is None:
                    upload = DfEngineGenerationUploads(generation_id=generation_id)
                upload.upload_status = UploadStatuses.success
                upload.uploaded_at = local_time()
                db.add(upload)

                result = db.query(DfEngineGenerationResults).filter_by(generation_id=generation_id).first()
                if result is None:
                    result = DfEngineGenerationResults(
                        generation_id=generation_id,
                        name=uploaded.get("name", ""),
                        path=uploaded.get("path", ""),
                        size=uploaded.get("size", 0),
                        md5=uploaded.get("md5"),
                    )
                else:
                    result.name = uploaded.get("name", result.name)
                    result.path = uploaded.get("path", result.path)
                    result.size = uploaded.get("size", result.size)
                    result.md5 = uploaded.get("md5", result.md5)
                db.add(result)
                generation = db.get(DfEngineGenerations, generation_id)
                generation.status = GenerationStatuses.success  # type: ignore
                db.add(generation)

            if task_id is not None:
                redis = sync_client()
                cache_key = CacheKeys()
                redis.delete(cache_key.user_galleries(user_id, task_id))
                delete_pattern_sync(redis, cache_key.references_picker_pattern(user_id))
                delete_pattern_sync(redis, cache_key.global_references_picker_pattern(user_id))
                delete_pattern_sync(redis, cache_key.user_files_pattern(user_id, task_id))

            return {"generation_id": generation_id, "status": "success", "result_id": result.id}
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
