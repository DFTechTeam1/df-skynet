import json
import asyncio
from decimal import Decimal
from log import logging
from typing import Any, Awaitable, Callable
from aio_pika import connect_robust
from aio_pika.abc import AbstractIncomingMessage
from sqlalchemy import update
from sqlalchemy.orm import selectinload
from apps.secret import DB_ASYNC_URL, RABBITMQ_URL
from error import ServiceError
from middlewares.lang import DEFAULT_LANG, resolve_message
from services.mysql import get_usd_rate, make_session, query
from schemas.format.openrouter import ChatAssistantResponse, PromptGuardrailResponse, TransferKnowledgeResponse
from services.mysql.model import (
    DfEngineApiKeys,
    DfEngineAttachments,
    DfEngineChatAssistants,
    DfEngineChatReferences,
    DfEngineChatSessions,
    DfEngineGuardrailValidations,
)
from services.chat_transcript import effective_chunk_tokens, estimate_tokens, single_call_limit, split_blocks
from services.openrouter import (
    TRANSFER_KNOWLEDGE_INSTRUCTION,
    TRANSFER_KNOWLEDGE_PROMPT,
    call_chat_assistant,
    call_prompt_guardrail,
)
from services.pusher import send_chat_assistant
from utils import local_time
from services.rmq.publisher import FAILED_QUEUE_NAME, QUEUE_NAME, build_message

MAX_PARALLEL = 2
MAX_RETRIES = 3


Handler = Callable[[dict[str, Any]], Awaitable[None]]
OnDead = Callable[[dict[str, Any], Exception], Awaitable[None]]


async def consume(handler: Handler, on_dead: OnDead | None = None) -> None:
    connection = await connect_robust(url=RABBITMQ_URL)
    async with connection:
        channel = await connection.channel()
        await channel.set_qos(prefetch_count=MAX_PARALLEL)
        queue = await channel.declare_queue(QUEUE_NAME, durable=True)
        await channel.declare_queue(FAILED_QUEUE_NAME, durable=True)

        async def on_message(message: AbstractIncomingMessage) -> None:
            async with message.process(requeue=True):
                header_retry = message.headers.get("x-retry", 0)
                retry = header_retry if isinstance(header_retry, int) else 0
                try:
                    await handler(json.loads(message.body))
                except Exception as exc:
                    logging.exception("queue message failed (retry %s/%s)", retry, MAX_RETRIES)
                    payload = json.loads(message.body)
                    if retry < MAX_RETRIES:
                        await asyncio.sleep(2**retry)
                        await channel.default_exchange.publish(
                            build_message(payload, retry + 1), routing_key=QUEUE_NAME
                        )
                    else:
                        if on_dead:
                            try:
                                await on_dead(payload, exc)
                            except Exception:
                                logging.exception("on_dead hook failed")
                        await channel.default_exchange.publish(
                            build_message(payload, retry), routing_key=FAILED_QUEUE_NAME
                        )

        await queue.consume(on_message)
        logging.info("consuming %s (parallel=%s, max_retries=%s)", QUEUE_NAME, MAX_PARALLEL, MAX_RETRIES)
        await asyncio.Future()


async def handle_guardrail_validation(payload: dict[str, Any]) -> None:
    is_guardrail_passed = True
    message = "Success"
    request_payload = {}
    request_response = {}
    status_code = 200
    total_tokens = 0
    cached_tokens = 0
    cost = 0
    exchange_rate = 0

    try:
        guardrail = await call_prompt_guardrail(
            messages=payload["guardrail"],
            api_key=payload["api_key"]["key"],
            model=payload["model"]["model_id"],
            user_id=payload["user_id"],
        )
        body = guardrail.json()
        request_payload = json.loads(guardrail.request.content)
        request_response = body
        status_code = guardrail.status_code
        usage = body.get("usage") or {}
        total_tokens = usage.get("total_tokens") or 0
        cached_tokens = (usage.get("prompt_tokens_details") or {}).get("cached_tokens") or 0
        cost = usage.get("cost") or 0

        formatted_response = PromptGuardrailResponse.model_validate_json(
            body["choices"][0]["message"]["content"], strict=True
        ).model_dump()

        if formatted_response["prompt_injection"] is True:
            message = resolve_message("guardrail_prompt_injection", payload["lang"])
            is_guardrail_passed = False

        elif formatted_response["nfsw"] is True:
            message = resolve_message("guardrail_nsfw", payload["lang"])
            is_guardrail_passed = False

        elif formatted_response["chat_assistant"] is False:
            message = resolve_message("guardrail_chat_assistant", payload["lang"])
            is_guardrail_passed = False

    except ServiceError as exc:
        ctx = exc.context or {}
        is_guardrail_passed = False
        message = resolve_message(exc.message, payload["lang"])
        request_payload = ctx.get("payload") or {}
        request_response = {"error": exc.error, "upstream_body": ctx.get("upstream_body")}
        status_code = (exc.error or {}).get("upstream_status", exc.status_code)

    async with make_session(DB_ASYNC_URL)() as db:
        exchange_rate = await db.run_sync(get_usd_rate)
        db.add(
            DfEngineGuardrailValidations(
                sourceable_id=payload["chat_id"],
                sourceable_type=DfEngineChatAssistants.__name__,
                apikeyable_id=payload["api_key"]["id"],
                apikeyable_type=DfEngineApiKeys.__name__,
                model_id=payload["model"]["id"],
                created_by=payload["user_id"],
                message=message,
                payload=request_payload,
                response=request_response,
                status_code=status_code,
                total_tokens=total_tokens,
                cached_tokens=cached_tokens,
                cost=Decimal(str(cost)),
                exchange_rate=exchange_rate,
            )
        )

        refusal = None
        if not is_guardrail_passed:
            refusal = DfEngineChatAssistants(
                session_id=payload["session_id"],
                role="assistant",
                model_id=payload["model"]["id"],
                apikeyable_id=payload["api_key"]["id"],
                apikeyable_type=DfEngineApiKeys.__name__,
                sender="openrouter",
                content=message,
                status_code=400,
            )
            db.add(refusal)
            await db.execute(
                update(DfEngineChatAssistants)
                .where(DfEngineChatAssistants.id == payload["chat_id"])
                .values(status_code=400)
            )
        await db.commit()
        refusal_uid = refusal.uid if refusal else None

    if refusal_uid:
        send_chat_assistant("failed", payload["session_uid"], refusal_uid)
        return

    await handle_chat_assistant(payload)


async def handle_chat_assistant(payload: dict[str, Any]) -> None:
    ok = True
    status_code = 200
    content = ""
    usage: dict[str, Any] = {}
    reply: ChatAssistantResponse | None = None

    try:
        result = await call_chat_assistant(
            messages=payload["content"],
            api_key=payload["api_key"]["key"],
            model=payload["model"]["model_id"],
            user_id=payload["user_id"],
        )
        body = result.json()
        status_code = result.status_code
        usage = body.get("usage") or {}
        reply = ChatAssistantResponse.model_validate_json(body["choices"][0]["message"]["content"], strict=True)
        content = reply.content
    except (ServiceError, ValueError, LookupError) as exc:
        logging.error("chat assistant failed for chat_id=%s: %r", payload["chat_id"], exc)
        ok = False
        content = resolve_message("chat_assistant_failed", payload["lang"])
        status_code = (
            (exc.error or {}).get("upstream_status", exc.status_code) if isinstance(exc, ServiceError) else 502
        )

    async with make_session(DB_ASYNC_URL)() as db:
        chat = DfEngineChatAssistants(
            session_id=payload["session_id"],
            role="assistant",
            model_id=payload["model"]["id"],
            apikeyable_id=payload["api_key"]["id"],
            apikeyable_type=DfEngineApiKeys.__name__,
            sender="openrouter",
            content=content,
            status_code=status_code,
            total_tokens=usage.get("total_tokens") or 0,
            cached_tokens=(usage.get("prompt_tokens_details") or {}).get("cached_tokens") or 0,
            cost=Decimal(str(usage.get("cost") or 0)),
            exchange_rate=await db.run_sync(get_usd_rate),
            has_generation_prompt=bool(reply and reply.has_generation_prompt),
        )
        db.add(chat)
        await db.flush()
        if not ok:
            await db.execute(
                update(DfEngineChatAssistants)
                .where(DfEngineChatAssistants.id == payload["chat_id"])
                .values(status_code=status_code)
            )

        # A generation prompt may use any image of the chat, so it is linked to all of them (user_chat refs stay as is).
        refs = payload.get("all_attachments", []) if reply and reply.has_generation_prompt else []
        refs = refs or payload.get("attachments", [])
        if refs:
            attachments = [
                DfEngineAttachments(sourceable_id=r["id"], sourceable_type=r["sourceable_type"]) for r in refs
            ]
            db.add_all(attachments)
            await db.flush()
            db.add_all([DfEngineChatReferences(chat_id=chat.id, attachment_id=a.id) for a in attachments])
        await db.commit()
        chat_uid = chat.uid

    send_chat_assistant("success" if ok else "failed", payload["session_uid"], chat_uid)


# A provider says "the prompt is too long" with one of these statuses. The wording differs per provider, so only the
# status is read.
TOO_LONG_STATUSES = (400, 413)


def _status_of(exc: ServiceError) -> int:
    """HTTP status of a failed provider call: the provider's own when we have it, else ours."""
    return (exc.error or {}).get("upstream_status", exc.status_code)


async def _summarise(payload: dict[str, Any], transcript: str, summary_so_far: str, usage: dict[str, Any]) -> str:
    """One summary call. Adds its tokens and cost to `usage` and returns the (updated) summary text."""
    parts = []
    if summary_so_far:
        parts.append(f"Summary so far:\n{summary_so_far}")
    parts.append(f"Chat to summarise:\n{transcript}")
    messages = [
        {"role": "system", "content": [{"type": "text", "text": TRANSFER_KNOWLEDGE_INSTRUCTION.strip()}]},
        {"role": "user", "content": [{"type": "text", "text": "\n\n".join(parts)}]},
    ]
    result = await call_chat_assistant(
        messages=messages,
        api_key=payload["api_key"]["key"],
        model=payload["model"]["model_id"],
        user_id=payload["user_id"],
        timeout=payload["timeout_seconds"],
        response_format=TransferKnowledgeResponse.response_format("transfer_summary"),
    )
    body = result.json()
    call_usage = body.get("usage") or {}
    usage["total_tokens"] += call_usage.get("total_tokens") or 0
    usage["cached_tokens"] += (call_usage.get("prompt_tokens_details") or {}).get("cached_tokens") or 0
    usage["cost"] += Decimal(str(call_usage.get("cost") or 0))
    reply = TransferKnowledgeResponse.model_validate_json(body["choices"][0]["message"]["content"], strict=True)
    return reply.summary.strip()


async def _summarise_in_chunks(
    payload: dict[str, Any], blocks: list[str], chunk_tokens: int, usage: dict[str, Any]
) -> str:
    """Summarise `blocks` chunk by chunk, each call getting the summary so far. Raises ServiceError when it cannot."""
    chunks = split_blocks(blocks, chunk_tokens)
    summary = ""
    calls = 0
    while chunks:
        if calls >= payload["max_chunks"]:
            raise ServiceError(
                status_code=502, message="chat_assistant_transfer_failed", error={"upstream_status": 502}
            )
        chunk = chunks.pop(0)
        calls += 1
        try:
            summary = await _summarise(payload, "\n\n".join(chunk), summary, usage)
        except ServiceError as exc:
            # a chunk the provider calls too long is retried once as two halves (the retry counts toward the cap)
            if _status_of(exc) in TOO_LONG_STATUSES and len(chunk) > 1:
                middle = len(chunk) // 2
                chunks[0:0] = [chunk[:middle], chunk[middle:]]
                continue
            raise
    return summary


async def _summarise_chat(payload: dict[str, Any], usage: dict[str, Any]) -> str:
    """The summary of the whole chat: one call when it fits the model, otherwise chunk by chunk.

    Chunks are used when the chat is too big for one call, when the model reports no window, or when the single
    call is refused as too long. Any other error (429, 5xx, timeout, rejected key) is raised: chunking would not
    help and would multiply the cost.
    """
    blocks: list[str] = payload["transcript_blocks"]
    top_provider = payload["model"].get("top_provider")

    one_call_limit = single_call_limit(payload["single_call_max_tokens"], top_provider)
    fits_one_call = one_call_limit > 0 and sum(estimate_tokens(block) for block in blocks) <= one_call_limit
    if fits_one_call:
        try:
            return await _summarise(payload, "\n\n".join(blocks), "", usage)
        except ServiceError as exc:
            if _status_of(exc) not in TOO_LONG_STATUSES:
                raise
            logging.warning("transfer single call refused (%s), using chunks", _status_of(exc))

    chunk_tokens = effective_chunk_tokens(payload["chunk_tokens"], top_provider)
    return await _summarise_in_chunks(payload, blocks, chunk_tokens, usage)


async def handle_transfer_knowledge(payload: dict[str, Any]) -> None:
    """Summarise the old chat and store the result as the first system message of the new session.

    Exactly one `system` row is written, and it always carries the cost of every summary call made:
    - success: the summary, status 200;
    - failure: the error text and the failure status, and the new session is archived (nothing is deleted).
    A `chat-response` push tells the client how it went. Provider errors are not raised: a retry would repeat
    paid calls.
    """
    usage: dict[str, Any] = {"total_tokens": 0, "cached_tokens": 0, "cost": Decimal("0")}

    try:
        summary = await _summarise_chat(payload, usage)
        succeeded = True
        content = TRANSFER_KNOWLEDGE_PROMPT.format(summary=summary).strip()
        status_code = 200
    except (ServiceError, ValueError, LookupError) as exc:
        logging.error("transfer knowledge failed for session_id=%s: %r", payload["session_id"], exc)
        succeeded = False
        content = resolve_message("chat_assistant_transfer_failed", payload["lang"])
        status_code = _status_of(exc) if isinstance(exc, ServiceError) else 502

    async with make_session(DB_ASYNC_URL)() as db:
        row = DfEngineChatAssistants(
            session_id=payload["session_id"],
            role="system",
            model_id=payload["model"]["id"],
            apikeyable_id=payload["api_key"]["id"],
            apikeyable_type=DfEngineApiKeys.__name__,
            sender="openrouter",
            content=content,
            status_code=status_code,
            total_tokens=usage["total_tokens"],
            cached_tokens=usage["cached_tokens"],
            cost=usage["cost"],
            exchange_rate=await db.run_sync(get_usd_rate),
        )
        db.add(row)
        if not succeeded:
            await db.execute(
                update(DfEngineChatSessions)
                .where(DfEngineChatSessions.id == payload["session_id"])
                .values(archieved_at=local_time())
            )
        await db.commit()
        row_uid = row.uid

    send_chat_assistant("success" if succeeded else "failed", payload["session_uid"], row_uid)


HANDLERS: dict[str, Handler] = {
    "guardrail_validation": handle_guardrail_validation,
    "chat_assistant": handle_chat_assistant,
    "transfer_knowledge": handle_transfer_knowledge,
}


async def dispatch(payload: dict[str, Any]) -> None:
    await HANDLERS[payload.get("type", "guardrail_validation")](payload)


if __name__ == "__main__":
    asyncio.run(consume(dispatch))
