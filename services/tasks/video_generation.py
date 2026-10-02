import json
from typing import Any, Optional
from celery.exceptions import SoftTimeLimitExceeded
from httpx import HTTPStatusError, NetworkError, TimeoutException
from apps.secret import OPENROUTER_BASE_URL
from config.variables import USD_TO_IDR_RATE
from services.api_caller import APICaller
from services.celery_app import celery_app
from services.dto import SyncedConnectionContext
from services.mysql import get_sync_db
from services.mysql.model import DfEngineGenerations
from services.mysql.model.df_engine_generations import GenerationStatuses
from services.redis import CacheKeys, get_json_sync, set_json_sync, sync_client
from services.tasks.base import (
    GenerationStageError,
    GenerationTask,
    classify_error,
    response_error_message,
    retry_countdown,
)
from services.tasks.udin_uploader import udin_uploader
from utils.formatter import format_idr, format_usd

POLL_INTERVAL_SECONDS = 10


@celery_app.task(
    bind=True,
    base=GenerationTask,
    name="df_engine.video_generation",
    retry_backoff=True,
    retry_backoff_max=60,
    retry_jitter=True,
    max_retries=5,
    soft_time_limit=30,
    time_limit=40,
    rate_limit="10/s",
)
def video_generation(
    self,
    generation_id: int,
    user_id: int,
    headers: Optional[dict[str, str]] = None,
    payload: Optional[dict[str, Any]] = None,
    is_poll: bool = False,
) -> dict[str, Any]:
    with get_sync_db() as db:
        ctx = SyncedConnectionContext(db, sync_client(), CacheKeys())
        generation = ctx.db.get(DfEngineGenerations, generation_id)
        if generation is None:
            raise ValueError("Generation record not found.")

        if generation.status == GenerationStatuses.success:
            return {"generation_id": generation_id, "status": "success", "skipped": True}
        if generation.response and generation.status_code == 200:
            return {"generation_id": generation_id, "status": "already_processed", "skipped": True}

        job = json.loads(generation.response) if generation.response else None
        if generation.status == GenerationStatuses.queued:
            generation.status = GenerationStatuses.processing
            ctx.db.add(generation)
        generation_detail_key = ctx.key.generation_detail(user_id, str(generation.uid))
        cached_generation_detail = get_json_sync(ctx.redis, generation_detail_key)
        if cached_generation_detail is not None:
            set_json_sync(ctx.redis, generation_detail_key, {**cached_generation_detail, "status": generation.status})

    caller = APICaller(base_url=OPENROUTER_BASE_URL, headers=headers or {})
    try:
        if job is None:
            response = caller.openrouter_sync("POST", "/videos", user_id=user_id, json=payload or {})
        else:
            response = caller.openrouter_sync("GET", job["polling_url"], user_id=user_id)
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

    if body["status"] in ("pending", "in_progress"):
        with get_sync_db() as db:
            ctx = SyncedConnectionContext(db, sync_client(), CacheKeys())
            generation = ctx.db.get(DfEngineGenerations, generation_id)
            generation.response = json.dumps({"polling_url": body["polling_url"]})  # type: ignore
            ctx.db.add(generation)

        video_generation.apply_async(  # type: ignore
            args=[generation_id, user_id],
            kwargs={"headers": headers, "is_poll": True},
            countdown=POLL_INTERVAL_SECONDS,
        )
        return {"generation_id": generation_id, "status": body["status"]}

    if body["status"] != "completed":
        raise GenerationStageError(
            f"openrouter video generation {body['status']}: {body.get('error', '')}",
            source="openrouter",
            final=True,
        )

    usage = body.get("usage", {})
    with get_sync_db() as db:
        ctx = SyncedConnectionContext(db, sync_client(), CacheKeys())
        generation = ctx.db.get(DfEngineGenerations, generation_id)
        generation.response = json.dumps({"polling_url": body["polling_url"]})  # type: ignore
        generation.status_code = response.status_code  # type: ignore
        generation.cost = usage.get("cost")  # type: ignore
        ctx.db.add(generation)
        generation_detail_key = ctx.key.generation_detail(user_id, str(generation.uid))  # type: ignore
        cached_generation_detail = get_json_sync(ctx.redis, generation_detail_key)
        if cached_generation_detail is not None:
            set_json_sync(
                ctx.redis,
                generation_detail_key,
                {
                    **cached_generation_detail,
                    "cost_usd": format_usd(generation.cost),  # type: ignore
                    "cost_idr": format_idr(generation.cost, USD_TO_IDR_RATE),  # type: ignore
                },
            )

    udin_uploader.delay(generation_id, user_id)  # type:ignore
    return {"generation_id": generation_id, "status": "openrouter_success"}
