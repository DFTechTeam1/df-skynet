import asyncio
import pytest
from services import rabbitmq


@pytest.mark.unit
async def test_publish_consume_roundtrip():
    try:
        await rabbitmq.get_channel()
    except Exception:
        pytest.skip("RabbitMQ not reachable")
    got: asyncio.Queue = asyncio.Queue()

    async def handler(msg):
        await got.put(msg)

    q = "test.roundtrip"
    await rabbitmq.consume(q, handler)
    await rabbitmq.publish(q, {"hello": "world"})
    assert await asyncio.wait_for(got.get(), 5) == {"hello": "world"}
    await rabbitmq.close()
