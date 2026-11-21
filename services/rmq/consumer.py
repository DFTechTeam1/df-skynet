import json
import asyncio
from decimal import Decimal
from typing import Any, Awaitable, Callable
from aio_pika import connect_robust
from aio_pika.abc import AbstractIncomingMessage
from sqlalchemy import update
from sqlalchemy.orm import selectinload
from apps.secret import DB_ASYNC_URL, RABBITMQ_URL
from error import ServiceError
from middlewares.lang import DEFAULT_LANG, resolve_message
from services.mysql import get_usd_rate, make_session, query
from enums.base import QueueStatuses
from schemas.format.pydantic_ai import ChatAttachment, ChatMessage, LLMResponse
from schemas.response import PromptGuardrailResponse
from services.mysql.model import (
    DfEngineApiKeys,
    DfEngineAttachments,
    DfEngineChatAssistants,
    DfEngineChatReferences,
    DfEngineGuardrailValidations,
)
from services.openrouter import call_prompt_guardrail
from utils.formatter import format_udin_url
from log import logging
from services.rmq.publisher import FAILED_QUEUE_NAME, QUEUE_NAME, build_message, publish_message

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
            prompt=payload["content"],
            api_key=payload["api_key"]["key"],
            rules=payload["guardrails"],
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

        if not is_guardrail_passed:
            db.add(
                DfEngineChatAssistants(
                    session_id=payload["session_id"],
                    role="assistant",
                    model_id=payload["model"]["id"],
                    apikeyable_id=payload["api_key"]["id"],
                    apikeyable_type=DfEngineApiKeys.__name__,
                    sender="openrouter",
                    content=message,
                    status=QueueStatuses.success,
                    status_code=400,
                )
            )
            await db.execute(
                update(DfEngineChatAssistants)
                .where(DfEngineChatAssistants.id == payload["chat_id"])
                .values(status_code=400)
            )
        await db.commit()


HANDLERS: dict[str, Handler] = {"guardrail_validation": handle_guardrail_validation}


async def dispatch(payload: dict[str, Any]) -> None:
    """Entry point for `consume()`: run the handler named by `payload["type"]`.

    Messages queued before `type` existed were guardrail checks, hence the default.
    An unknown type raises, so it is retried and then lands in the failed queue.
    """
    await HANDLERS[payload.get("type", "guardrail_validation")](payload)


if __name__ == "__main__":
    asyncio.run(consume(dispatch))
