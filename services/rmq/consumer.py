import aiormq
from apps.secret import RABBITMQ_URL
from aio_pika import connect_robust

QUEUE_NAME = "chat_asistant_queue"


async def connect() -> None:
    connection = await connect_robust(url=RABBITMQ_URL)

    async with connection:
        channel = await connection.channel()
        queue = channel.declare_queue(name=QUEUE_NAME, durable=True, timeout=5, auto_delete=True)
