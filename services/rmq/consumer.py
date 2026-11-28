import json
import asyncio
from decimal import Decimal
from typing import Any, Awaitable, Callable
from aio_pika import connect_robust
from aio_pika.abc import AbstractChannel, AbstractIncomingMessage
from sqlalchemy import update
from apps.secret import DB_ASYNC_URL, RABBITMQ_URL
from error import ServiceError
from log import logging
from middlewares.lang import resolve_message
from schemas.format.openrouter import ChatAssistantResponse, PromptGuardrailResponse, TransferKnowledgeResponse
from services.chat_transcript import effective_chunk_tokens, estimate_tokens, single_call_limit, split_blocks
from services.mysql import get_usd_rate, make_session
from services.mysql.model import (
    DfEngineApiKeys,
    DfEngineAttachments,
    DfEngineChatAssistants,
    DfEngineChatReferences,
    DfEngineChatSessions,
    DfEngineGuardrailValidations,
)
from services.openrouter import (
    TRANSFER_KNOWLEDGE_INSTRUCTION,
    TRANSFER_KNOWLEDGE_PROMPT,
    call_chat_assistant,
    call_prompt_guardrail,
)
from services.pusher import send_chat_assistant
from services.repository.chat_assistants import ChatAssistantRepository
from services.repository.guardrail_validations import GuardrailValidationRepository
from services.rmq.publisher import FAILED_QUEUE_NAME, QUEUE_NAME, build_message
from utils import local_time

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
            await process(channel, message, handler, on_dead)

        await queue.consume(on_message)
        logging.info("consuming %s (parallel=%s, max_retries=%s)", QUEUE_NAME, MAX_PARALLEL, MAX_RETRIES)
        await asyncio.Future()


async def process(
    channel: AbstractChannel, message: AbstractIncomingMessage, handler: Handler, on_dead: OnDead | None
) -> None:
    """Run the handler for one message.

    A failed message is republished with `x-retry + 1` (after a 1s/2s/4s pause), or sent to the failed queue once it
    is out of retries. The original is acked when the block exits; if the process dies before that, the broker
    redelivers it (the handlers are idempotent, see `replay_if_done`).
    """
    async with message.process(requeue=True):
        header_retry = message.headers.get("x-retry", 0)
        retry = header_retry if isinstance(header_retry, int) else 0
        payload = json.loads(message.body)
        try:
            await handler(payload)
        except Exception as exc:
            logging.exception("queue message failed (retry %s/%s)", retry, MAX_RETRIES)
            if retry < MAX_RETRIES:
                await asyncio.sleep(2**retry)
                await channel.default_exchange.publish(build_message(payload, retry + 1), routing_key=QUEUE_NAME)
            else:
                await dead_letter(channel, payload, retry, exc, on_dead)


async def dead_letter(
    channel: AbstractChannel, payload: dict[str, Any], retry: int, exc: Exception, on_dead: OnDead | None
) -> None:
    """Out of retries: tell `on_dead` (its own errors are only logged), then park the message in the failed queue."""
    if on_dead:
        try:
            await on_dead(payload, exc)
        except Exception:
            logging.exception("on_dead hook failed")
    await channel.default_exchange.publish(build_message(payload, retry), routing_key=FAILED_QUEUE_NAME)


async def replay_if_done(payload: dict[str, Any]) -> bool:
    """True when this message already wrote its reply (it was redelivered after a crash before the ack).

    The push is sent again, because the crash may have happened before it. Old messages (no message_id) never match.
    """
    if not payload.get("message_id"):
        return False
    async with make_session(DB_ASYNC_URL)() as db:
        reply = await ChatAssistantRepository(db).get_chat_assistant(
            filters=(DfEngineChatAssistants.message_id == payload["message_id"],),
            columns=(DfEngineChatAssistants.uid, DfEngineChatAssistants.status_code),
            raise_if_null=False,
        )
    if reply is None:
        return False
    logging.warning("message %s already handled, skipping", payload["message_id"])
    send_chat_assistant("success" if reply["status_code"] == 200 else "failed", payload["session_uid"], reply["uid"])
    return True


async def guardrail_done(payload: dict[str, Any]) -> bool:
    """True when this message's guardrail was already saved, so a retry does not pay for it twice."""
    if not payload.get("message_id"):
        return False
    async with make_session(DB_ASYNC_URL)() as db:
        found = await GuardrailValidationRepository(db).get_guardrail_validation(
            filters=(DfEngineGuardrailValidations.message_id == payload["message_id"],),
            columns=(DfEngineGuardrailValidations.id,),
            raise_if_null=False,
        )
    return found is not None


def token_counts(usage: dict[str, Any]) -> tuple[int, int]:
    """(total_tokens, cached_tokens) of a provider `usage` block; missing values count as 0."""
    cached = (usage.get("prompt_tokens_details") or {}).get("cached_tokens") or 0
    return usage.get("total_tokens") or 0, cached


def with_reference_tags(content: str, refs: list[dict[str, Any]]) -> str:
    """`content` with a `<refer to {uid}>` tag at the end for every file in `refs` the text does not mention yet.

    A reply that carries files always names them in its text, whatever the model wrote.
    """
    missing = [uid for uid in dict.fromkeys(r["uid"] for r in refs) if f"<refer to {uid}>" not in content]
    if not missing:
        return content
    return content + "\n\n" + "\n".join(f"<refer to {uid}>" for uid in missing)


def assistant_row(
    payload: dict[str, Any], role: str, content: str, status_code: int, **extra: Any
) -> DfEngineChatAssistants:
    """A chat row written by the engine (reply, refusal or transfer summary), stamped with the message's id."""
    return DfEngineChatAssistants(
        session_id=payload["session_id"],
        role=role,
        model_id=payload["model"]["id"],
        apikeyable_id=payload["api_key"]["id"],
        apikeyable_type=DfEngineApiKeys.__name__,
        content=content,
        status_code=status_code,
        message_id=payload.get("message_id"),
        **extra,
    )


async def run_guardrail(payload: dict[str, Any]) -> tuple[bool, dict[str, Any]]:
    """Call the guardrail model. Returns (passed, fields of the DfEngineGuardrailValidations row)."""
    passed = True
    fields: dict[str, Any] = {
        "message": "Success",
        "payload": {},
        "response": {},
        "status_code": 200,
        "total_tokens": 0,
        "cached_tokens": 0,
        "cost": Decimal("0"),
    }

    try:
        guardrail = await call_prompt_guardrail(
            messages=payload["guardrail"],
            api_key=payload["api_key"]["key"],
            model=payload["model"]["model_id"],
            user_id=payload["user_id"],
        )
        body = guardrail.json()
        usage = body.get("usage") or {}
        fields["payload"] = json.loads(guardrail.request.content)
        fields["response"] = body
        fields["status_code"] = guardrail.status_code
        fields["total_tokens"], fields["cached_tokens"] = token_counts(usage)
        fields["cost"] = Decimal(str(usage.get("cost") or 0))

        verdict = PromptGuardrailResponse.model_validate_json(
            body["choices"][0]["message"]["content"], strict=True
        ).model_dump()

        if verdict["prompt_injection"] is True:
            fields["message"] = resolve_message("guardrail_prompt_injection", payload["lang"])
            passed = False

        elif verdict["nfsw"] is True:
            fields["message"] = resolve_message("guardrail_nsfw", payload["lang"])
            passed = False

        elif verdict["chat_assistant"] is False:
            fields["message"] = resolve_message("guardrail_chat_assistant", payload["lang"])
            passed = False

    except ServiceError as exc:
        ctx = exc.context or {}
        passed = False
        fields["message"] = resolve_message(exc.message, payload["lang"])
        fields["payload"] = ctx.get("payload") or {}
        fields["response"] = {"error": exc.error, "upstream_body": ctx.get("upstream_body")}
        fields["status_code"] = (exc.error or {}).get("upstream_status", exc.status_code)

    return passed, fields


TOO_LONG_STATUSES = (400, 413)


def status_of(exc: ServiceError) -> int:
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
    total_tokens, cached_tokens = token_counts(call_usage)
    usage["total_tokens"] += total_tokens
    usage["cached_tokens"] += cached_tokens
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
            if status_of(exc) in TOO_LONG_STATUSES and len(chunk) > 1:
                middle = len(chunk) // 2
                chunks[0:0] = [chunk[:middle], chunk[middle:]]
                continue
            raise
    return summary


async def summarise_chat(payload: dict[str, Any], usage: dict[str, Any]) -> str:
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
            if status_of(exc) not in TOO_LONG_STATUSES:
                raise
            logging.warning("transfer single call refused (%s), using chunks", status_of(exc))

    chunk_tokens = effective_chunk_tokens(payload["chunk_tokens"], top_provider)
    return await _summarise_in_chunks(payload, blocks, chunk_tokens, usage)


async def handle_guardrail_validation(payload: dict[str, Any]) -> None:
    if await guardrail_done(payload):
        await handle_chat_assistant(payload)
        return

    passed, fields = await run_guardrail(payload)

    async with make_session(DB_ASYNC_URL)() as db:
        db.add(
            DfEngineGuardrailValidations(
                sourceable_id=payload["chat_id"],
                sourceable_type=DfEngineChatAssistants.__name__,
                apikeyable_id=payload["api_key"]["id"],
                apikeyable_type=DfEngineApiKeys.__name__,
                model_id=payload["model"]["id"],
                created_by=payload["user_id"],
                exchange_rate=await db.run_sync(get_usd_rate),
                message_id=payload.get("message_id"),
                **fields,
            )
        )

        refusal = None
        if not passed:
            refusal = assistant_row(payload, "assistant", fields["message"], 400)
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


def openrouter_error(body: Any) -> str | None:
    """`error.message` of an OpenRouter response body (dict or raw JSON text), or None when it is missing or blank."""
    if isinstance(body, str):
        try:
            body = json.loads(body)
        except ValueError:
            return None
    if not isinstance(body, dict):
        return None
    error = body.get("error") or ((body.get("choices") or [{}])[0] or {}).get("error")
    message = error.get("message") if isinstance(error, dict) else None
    return (message.strip() or None) if isinstance(message, str) else None


async def handle_chat_assistant(payload: dict[str, Any]) -> None:
    if await replay_if_done(payload):
        return

    ok = True
    status_code = 200
    content = ""
    usage: dict[str, Any] = {}
    reply: ChatAssistantResponse | None = None
    body: Any = {}

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
        source = (exc.context or {}).get("upstream_body") if isinstance(exc, ServiceError) else body
        content = openrouter_error(source) or resolve_message("chat_assistant_failed", payload["lang"])
        status_code = (
            (exc.error or {}).get("upstream_status", exc.status_code) if isinstance(exc, ServiceError) else 502
        )

    has_prompt = bool(reply and reply.has_generation_prompt)
    will_prompt = bool(reply and reply.will_generate_prompt)
    if has_prompt and not payload.get("generate_prompt"):
        logging.warning("prompt written without a yes for chat_id=%s, asking first", payload["chat_id"])
        content = resolve_message("chat_assistant_confirm_generate_prompt", payload["lang"])
        has_prompt, will_prompt = False, True
    will_prompt = will_prompt and not has_prompt

    # The files this reply carries (every file of the chat for a written prompt, else the message's own)
    refs = (payload.get("all_attachments", []) if has_prompt else []) or payload.get("attachments", [])
    content = with_reference_tags(content, refs)

    total_tokens, cached_tokens = token_counts(usage)
    async with make_session(DB_ASYNC_URL)() as db:
        chat = assistant_row(
            payload,
            "assistant",
            content,
            status_code,
            total_tokens=total_tokens,
            cached_tokens=cached_tokens,
            cost=Decimal(str(usage.get("cost") or 0)),
            exchange_rate=await db.run_sync(get_usd_rate),
            has_generation_prompt=has_prompt,
            will_generate_prompt=will_prompt,
        )
        db.add(chat)
        await db.flush()
        if not ok:
            await db.execute(
                update(DfEngineChatAssistants)
                .where(DfEngineChatAssistants.id == payload["chat_id"])
                .values(status_code=status_code)
            )

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


async def handle_transfer_knowledge(payload: dict[str, Any]) -> None:
    """Summarise the old chat and store the result as the first system message of the new session.

    Exactly one `system` row is written, and it always carries the cost of every summary call made:
    - success: the summary, status 200;
    - failure: the error text and the failure status, and the new session is archived (nothing is deleted).
    A `chat-response` push tells the client how it went. Provider errors are not raised: a retry would repeat
    paid calls.
    """
    if await replay_if_done(payload):
        return

    usage: dict[str, Any] = {"total_tokens": 0, "cached_tokens": 0, "cost": Decimal("0")}

    try:
        summary = await summarise_chat(payload, usage)
        succeeded = True
        content = TRANSFER_KNOWLEDGE_PROMPT.format(summary=summary).strip()
        status_code = 200
    except (ServiceError, ValueError, LookupError) as exc:
        logging.error("transfer knowledge failed for session_id=%s: %r", payload["session_id"], exc)
        succeeded = False
        content = resolve_message("chat_assistant_transfer_failed", payload["lang"])
        status_code = status_of(exc) if isinstance(exc, ServiceError) else 502

    async with make_session(DB_ASYNC_URL)() as db:
        row = assistant_row(
            payload,
            "system",
            content,
            status_code,
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
