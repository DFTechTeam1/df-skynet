from sqlalchemy.orm import load_only
import random
import time
import httpx
from typing import Literal
from typing import Any, Optional
from billiard.exceptions import SoftTimeLimitExceeded
from billiard.einfo import ExceptionInfo
from celery.exceptions import Retry
from celery.utils.time import get_exponential_backoff_interval
from log import logging
from services.celery_app import celery_app
from services.mysql import get_sync_db
from services.mysql.model import DfEngineGenerations, DfEngineQueues, ProjectSongLists, ProjectTasks, Projects, Users
from services.mysql.model.df_engine_generations import GenerationStatuses
from services.mysql.model.df_engine_queues import QueueEventTypes
from services.pusher import broadcast_generation_status
from services.redis import CacheKeys, delete_pattern_sync, invalidate_project_files_sync, sync_client


class GenerationStageError(Exception):
    def __init__(
        self,
        message: str,
        source: Literal["udin", "openrouter"],
        status_code: Optional[int] = None,
        retryable: bool = False,
        final: bool = False,
    ) -> None:
        super().__init__(message)
        self.source = source
        self.status_code = status_code
        self.retryable = retryable
        self.final = final

    def __reduce__(self):
        return (self.__class__, (str(self), self.source, self.status_code, self.retryable, self.final))


def _plain_error_text(response: httpx.Response) -> str:
    """A non-JSON error body is usually a proxy's HTML error page (e.g. Cloudflare's 524, ~6 KB), which would be
    stored in full on every retry row. Keep only a one-line summary for those."""
    text = response.text or ""
    if text.lstrip()[:1] == "<":
        return f"HTTP {response.status_code} (non-JSON error page from {response.request.url.host})"
    return text or f"HTTP {response.status_code}"


def response_error_message(response: httpx.Response) -> str:
    try:
        body = response.json()
    except ValueError:
        return _plain_error_text(response)
    error = body.get("error")
    if isinstance(error, dict):
        return error.get("message") or str(error)
    return error or body.get("message") or _plain_error_text(response)


def classify_error(exc: Exception, source: Literal["udin", "openrouter"]) -> GenerationStageError:
    if isinstance(exc, SoftTimeLimitExceeded):
        return GenerationStageError(str(exc), source=source, retryable=True)

    if isinstance(exc, httpx.HTTPStatusError):
        status_code = exc.response.status_code
        return GenerationStageError(str(exc), source=source, status_code=status_code, retryable=True, final=False)

    if isinstance(exc, (httpx.TimeoutException, httpx.NetworkError)):
        return GenerationStageError(str(exc), source=source, retryable=True)

    return GenerationStageError(str(exc), source=source, retryable=False, final=True)


def retry_countdown(task) -> int:
    """Exponential backoff (1, 2, 4, 8... capped at `retry_backoff_max`) with half-jitter when `retry_jitter` is on:
    a random delay in [backoff/2, backoff]. Celery's own full jitter picks anywhere in [0, backoff], which often
    returned 0-1s and re-sent the request straight into the same stuck connection."""
    backoff = get_exponential_backoff_interval(
        factor=1,
        retries=task.request.retries,
        maximum=task.retry_backoff_max,
        full_jitter=False,
    )
    return random.randint(backoff // 2, backoff) if task.retry_jitter else backoff


def log_queue(
    generation_id: int,
    queue_name: str,
    event_type: QueueEventTypes,
    attempt: int,
    task_id: str,
    detail: Optional[dict[str, Any]] = None,
    duration_ms: Optional[int] = None,
) -> None:
    try:
        with get_sync_db() as db:
            db.add(
                DfEngineQueues(
                    generation_id=generation_id,
                    queue_name=queue_name,
                    event_type=event_type,
                    attempt=attempt,
                    duration_ms=duration_ms,
                    detail={"celery_task_id": task_id, **(detail or {})},
                )
            )
    except Exception:
        logging.exception(f"failed to write df_engine_queues event={event_type}")


def _generation_broadcast_context(generation_id: int, user_id: int) -> Optional[tuple[str, str, str, str]]:
    """Returns (gid, project_uid, task_or_song_uid, user_uid) for the pusher channel, or None if any is missing
    (including an orphan whose task/song was deleted, which has nothing to broadcast to)."""
    try:
        with get_sync_db() as db:
            row = (
                db.query(DfEngineGenerations.uid, Projects.uid, ProjectTasks.uid, ProjectSongLists.uid)
                .outerjoin(Projects, Projects.id == DfEngineGenerations.project_id)
                .outerjoin(ProjectTasks, ProjectTasks.id == DfEngineGenerations.task_id)
                .outerjoin(ProjectSongLists, ProjectSongLists.id == DfEngineGenerations.song_id)
                .filter(DfEngineGenerations.id == generation_id)
                .first()
            )
            if row is None or row[1] is None or (row[2] or row[3]) is None:
                return None
            user_row = db.query(Users.uid).filter(Users.id == user_id).first()
            if user_row is None:
                return None
        return str(row[0]), str(row[1]), str(row[2] or row[3]), str(user_row[0])
    except Exception:
        logging.exception(f"failed to resolve generation broadcast context generation_id={generation_id}")
        return None


def _mark_generation_failed(generation_id: int) -> None:
    try:
        with get_sync_db() as db:
            generation = db.get(
                DfEngineGenerations,
                generation_id,
                options=[
                    load_only(DfEngineGenerations.status, DfEngineGenerations.task_id, DfEngineGenerations.project_id)
                ],
            )
            if generation is None or generation.status == GenerationStatuses.success:
                return
            generation.status = GenerationStatuses.failed
            db.add(generation)
            task_id, project_id = generation.task_id, generation.project_id
        if task_id is not None:
            delete_pattern_sync(sync_client(), CacheKeys().generation_files_main_list_pattern(task_id))
        if project_id is not None:
            invalidate_project_files_sync(sync_client(), CacheKeys(), project_id)
    except Exception:
        logging.exception(f"failed to mark generation failed generation_id={generation_id}")


STAGE_STATUSES = {
    "df_engine.image_generation": "generating",
    "df_engine.video_generation": "generating",
    "df_engine.udin_uploader": "uploading",
}


def _release_reupload_lock(generation_id: int) -> None:
    """Free the manual re-upload lock once the task is terminal, so a failed manual upload can be retried right away."""
    try:
        sync_client().delete(CacheKeys().generation_reupload_lock(generation_id))
    except Exception:
        logging.exception(f"failed to release reupload lock generation_id={generation_id}")


MAX_REDELIVERIES = 3  # same task id + same attempt logged `started` this many times = worker keeps dying on it


def _redelivery_count(generation_id: int, task_id: str, attempt: int) -> int:
    with get_sync_db() as db:
        return (
            db.query(DfEngineQueues.id)
            .filter(
                DfEngineQueues.generation_id == generation_id,
                DfEngineQueues.event_type == QueueEventTypes.started,
                DfEngineQueues.attempt == attempt,
                DfEngineQueues.detail["celery_task_id"].as_string() == task_id,  # type: ignore
            )
            .count()
        )


class GenerationTask(celery_app.Task):
    def _attempt_duration_ms(self) -> Optional[int]:
        """Milliseconds since this attempt's `before_start`, or None if it never ran. The start time lives on
        `self.request`, which Celery creates per execution, so concurrent tasks and retries never share it."""
        started_at = getattr(self.request, "attempt_started_at", None)
        return None if started_at is None else int((time.perf_counter() - started_at) * 1000)

    def before_start(self, task_id: str, args: tuple, kwargs: dict[str, Any]) -> None:
        self.request.attempt_started_at = time.perf_counter()
        generation_id = args[0] if args else kwargs["generation_id"]
        attempt = self.request.retries + 1
        try:
            redeliveries = _redelivery_count(generation_id, task_id, attempt)
        except Exception:
            logging.exception(f"failed to count redeliveries generation_id={generation_id}")
            redeliveries = 0
        if redeliveries >= MAX_REDELIVERIES - 1:
            # raised from before_start, Celery routes this to on_failure (marks failed) and acks the message
            raise GenerationStageError(
                f"task redelivered {redeliveries + 1} times without finishing (worker killed?)",
                source="udin" if self.name == "df_engine.udin_uploader" else "openrouter",
                final=True,
            )
        log_queue(
            generation_id=generation_id,
            queue_name=self.name,
            event_type=QueueEventTypes.started,
            attempt=self.request.retries + 1,
            task_id=task_id,
        )
        if kwargs.get("is_poll"):
            return  # re-queued poll tick, not a stage change - skip the Pusher spam

        user_id = args[1] if len(args) > 1 else kwargs["user_id"]
        context = _generation_broadcast_context(generation_id, user_id)
        if context:
            gid, project_uid, task_uid, user_uid = context
            broadcast_generation_status(
                project_uid, task_uid, user_uid, gid, STAGE_STATUSES.get(self.name, "processing")
            )

    def on_retry(self, exc: Exception, task_id: str, args: tuple, kwargs: dict[str, Any], einfo: ExceptionInfo) -> None:
        detail = (
            {"source": exc.source, "status_code": exc.status_code, "message": str(exc)}
            if isinstance(exc, GenerationStageError)
            else {"message": str(exc)}
        )
        generation_id = args[0] if args else kwargs["generation_id"]
        log_queue(
            generation_id=generation_id,
            queue_name=self.name,
            event_type=QueueEventTypes.retried,
            attempt=self.request.retries + 1,
            task_id=task_id,
            duration_ms=self._attempt_duration_ms(),
            detail=detail,
        )
        user_id = args[1] if len(args) > 1 else kwargs["user_id"]
        context = _generation_broadcast_context(generation_id, user_id)
        if context:
            gid, project_uid, task_uid, user_uid = context
            broadcast_generation_status(project_uid, task_uid, user_uid, gid, "retry", error=str(exc))

    def on_success(self, retval: Any, task_id: str, args: tuple, kwargs: dict) -> None:
        _release_reupload_lock(args[0] if args else kwargs["generation_id"])
        log_queue(
            generation_id=args[0] if args else kwargs["generation_id"],
            queue_name=self.name,
            event_type=QueueEventTypes.succeeded,
            attempt=self.request.retries + 1,
            task_id=task_id,
            duration_ms=self._attempt_duration_ms(),
            detail={k: v for k, v in retval.items() if k != "generation_id"} if isinstance(retval, dict) else None,
        )

    def on_failure(self, exc: Exception, task_id: str, args: tuple, kwargs: dict, einfo: ExceptionInfo) -> None:
        if isinstance(exc, Retry):
            return

        detail = (
            {
                "source": exc.source,
                "status_code": exc.status_code,
                "final": exc.final,
                "message": str(exc),
            }
            if isinstance(exc, GenerationStageError)
            else {"message": str(exc)}
        )
        generation_id = args[0] if args else kwargs["generation_id"]
        _release_reupload_lock(generation_id)
        _mark_generation_failed(generation_id)
        log_queue(
            generation_id=generation_id,
            queue_name=self.name,
            event_type=QueueEventTypes.failed,
            attempt=self.request.retries + 1,
            task_id=task_id,
            duration_ms=self._attempt_duration_ms(),
            detail=detail,
        )
        user_id = args[1] if len(args) > 1 else kwargs["user_id"]
        context = _generation_broadcast_context(generation_id, user_id)
        if context:
            gid, project_uid, task_uid, user_uid = context
            broadcast_generation_status(project_uid, task_uid, user_uid, gid, "failed", error=str(exc))
