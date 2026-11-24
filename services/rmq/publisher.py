import json
from asyncio import Lock
from typing import Any, Optional
from uuid import uuid4
from aio_pika import DeliveryMode, Message, connect_robust
from aio_pika.abc import AbstractChannel, AbstractRobustConnection
from fastapi import status
from apps.secret import RABBITMQ_URL
from error import ServiceError
from log import logging

QUEUE_NAME = "chat_assistant_queue"
FAILED_QUEUE_NAME = f"{QUEUE_NAME}.failed"

connection: Optional[AbstractRobustConnection] = None
channel: Optional[AbstractChannel] = None
lock = Lock()


def build_message(payload: dict[str, Any], retry: int = 0) -> Message:
    return Message(
        body=json.dumps(payload, default=str).encode(),
        content_type="application/json",
        delivery_mode=DeliveryMode.PERSISTENT,
        headers={"x-retry": retry},
    )


async def get_channel() -> AbstractChannel:
    global connection, channel
    async with lock:
        if connection is None or connection.is_closed:
            connection = await connect_robust(url=RABBITMQ_URL, timeout=10)
            channel = None
        if channel is None or channel.is_closed:
            channel = await connection.channel()
            await channel.declare_queue(QUEUE_NAME, durable=True)
        return channel


async def publish_message(payload: dict[str, Any]) -> None:
    try:
        payload.setdefault("message_id", str(uuid4()))
        channel = await get_channel()
        await channel.default_exchange.publish(build_message(payload), routing_key=QUEUE_NAME)
    except Exception as exc:
        logging.exception("failed to publish to %s", QUEUE_NAME)
        raise ServiceError(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, message="chat_queue_unavailable") from exc
