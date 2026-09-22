from typing import Any, Optional
from celery.exceptions import SoftTimeLimitExceeded
from httpx import HTTPStatusError, NetworkError, TimeoutException
from apps.secret import OPENROUTER_BASE_URL
from services.api_caller import APICaller
from services.celery_app import celery_app
from services.mysql import get_sync_db
from services.mysql.model import DfEngineGenerations
from services.mysql.model.df_engine_generations import GenerationStatuses
from services.tasks.base import GenerationTask, classify_error, response_error_message, retry_countdown
from services.tasks.udin_uploader import udin_uploader


@celery_app.task(
    bind=True,
    base=GenerationTask,
    name="df_engine.image_generation",
    retry_backoff=True,
    retry_backoff_max=60,
    retry_jitter=True,
    max_retries=5,
    soft_time_limit=280,
    time_limit=300,
    rate_limit="10/s",
)
def image_generation(
    self,
    generation_id: int,
    user_id: int,
    headers: Optional[dict[str, str]] = None,
    payload: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    with get_sync_db() as db:
        generation = db.get(DfEngineGenerations, generation_id)
        if generation is None:
            raise ValueError("Generation record not found.")

        if generation.status == GenerationStatuses.success:
            return {"generation_id": generation_id, "status": "success", "skipped": True}

        if generation.response and generation.status_code == 200:
            return {"generation_id": generation_id, "status": "already_processed", "skipped": True}

        generation.status = GenerationStatuses.processing
        db.add(generation)

    caller = APICaller(base_url=OPENROUTER_BASE_URL, headers=headers or {})
    try:
        response = caller.openrouter_sync("POST", "/images", user_id=user_id, json=payload or {})
    except (TimeoutException, NetworkError, SoftTimeLimitExceeded) as exc:
        stage_error = classify_error(exc, source="openrouter")
        if stage_error.retryable and self.request.retries < self.max_retries:
            raise self.retry(exc=stage_error, countdown=retry_countdown(self))
        raise stage_error
    finally:
        caller.sync_client.close()

    if response.is_error:
        stage_error = classify_error(
            HTTPStatusError(response_error_message(response), request=response.request, response=response),
            source="openrouter",
        )
        if stage_error.retryable and self.request.retries < self.max_retries:
            raise self.retry(exc=stage_error, countdown=retry_countdown(self))
        raise stage_error

    body = response.json()
    usage = body.get("usage", {})
    with get_sync_db() as db:
        generation = db.get(DfEngineGenerations, generation_id)
        generation.response = body["data"][0]["b64_json"]  # type: ignore
        generation.status_code = response.status_code  # type: ignore
        generation.token_usage = usage.get("total_tokens")  # type: ignore
        generation.cost = usage.get("cost")  # type: ignore
        db.add(generation)

    udin_uploader.delay(generation_id, user_id)  # type:ignore
    return {"generation_id": generation_id, "status": "openrouter_success"}
