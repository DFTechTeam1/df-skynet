import asyncio
import re
from typing import Any, Optional
from error import BaseError
from services.celery_app import celery_app
from services.dto import SyncedConnectionContext
from services.mysql import get_sync_db, get_usd_rate
from services.mysql.model import DfEngineGenerations
from services.mysql.model.df_engine_generations import GenerationStatuses
from services.pusher import broadcast_prompt_enhancer
from services.redis import CacheKeys, set_json_sync, sync_client
from services.tasks.base import GenerationStageError, GenerationTask, _generation_broadcast_context
from validations.prompt import enhance_prompt

ENHANCE_TIMEOUT = 90


class EnhanceTask(GenerationTask):
    def _broadcast(
        self, project_uid: str, task_uid: str, user_id: int, gid: str, status: str, error: Optional[str] = None
    ) -> None:
        if status == "failed":
            broadcast_prompt_enhancer(project_uid, task_uid, user_id, gid, "failed", error)


def normalize_reference_tags(text: str, reference_uids: list[str]) -> str:
    """Normalize every user-passed uid to the template format `<refer to uid>`."""
    for uid in reference_uids:
        text = re.sub(rf"(?<!<refer to ){re.escape(uid)}", f"<refer to {uid}>", text)
        if f"<refer to {uid}>" not in text:
            text += f" <refer to {uid}>"
    return text


@celery_app.task(
    bind=True,
    base=EnhanceTask,
    name="df_engine.prompt_enhancement",
    max_retries=0,
    soft_time_limit=120,
    time_limit=150,
)
def prompt_enhancement(
    self,
    generation_id: int,
    user_id: int,
    api_key: str,
    model_id: str,
    enhancer_input: str,
    image_urls: list[str],
    reference_uids: list[str],
) -> dict[str, Any]:
    with get_sync_db() as db:
        generation = db.get(DfEngineGenerations, generation_id)
        if generation is None:
            raise ValueError("Generation record not found.")
        if generation.status == GenerationStatuses.success:
            return {"generation_id": generation_id, "status": "success", "skipped": True}
        generation.status = GenerationStatuses.processing
        db.add(generation)

    try:
        enhanced = asyncio.run(
            enhance_prompt(enhancer_input, model_id, api_key, user_id, image_urls, timeout=ENHANCE_TIMEOUT)
        )
    except BaseError as exc:
        raise GenerationStageError(exc.message, source="openrouter", final=True)

    text = normalize_reference_tags(enhanced["text"], reference_uids)
    with get_sync_db() as db:
        ctx = SyncedConnectionContext(db, sync_client(), CacheKeys())
        generation = db.get(DfEngineGenerations, generation_id)
        generation.response = text  # type: ignore
        generation.status = GenerationStatuses.success  # type: ignore
        generation.status_code = enhanced["status_code"]  # type: ignore
        generation.token_usage = enhanced["usage"].get("total_tokens")  # type: ignore
        generation.cost = enhanced["usage"].get("cost")  # type: ignore
        generation.exchange_rate = get_usd_rate(db)  # type: ignore
        db.add(generation)
        set_json_sync(
            ctx.redis,
            ctx.key.enhancer_detail(str(generation.uid)),
            {
                "id": generation.id,
                "prompt": generation.prompt,
                "full_prompt": generation.full_prompt,
                "response": text,
                "enhance_uid": str(generation.uid),
            },
        )

    context = _generation_broadcast_context(generation_id, user_id)
    if context:
        gid, project_uid, task_uid, user_id = context
        broadcast_prompt_enhancer(project_uid, task_uid, user_id, gid, "success")
    return {"generation_id": generation_id, "status": "success"}
