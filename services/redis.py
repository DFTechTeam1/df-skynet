import json
from functools import lru_cache
from typing import Any, Optional
from redis.asyncio import Redis
from redis.exceptions import AuthenticationError as RedisAuthError
from apps.secret import REDIS_HOST, REDIS_PASSWORD, REDIS_PORT
from error import AuthenticationError, ServiceError


@lru_cache
def client() -> Redis:
    return Redis(host=REDIS_HOST, port=REDIS_PORT, password=REDIS_PASSWORD)


async def get_redis() -> Redis:
    """FastAPI dependency: hand back the shared client, checking it's alive."""
    redis = client()
    try:
        await redis.ping()
    except RedisAuthError:
        raise AuthenticationError(
            message="Failed to connect to Redis. Please check your credentials and connection settings."
        )
    except Exception:
        raise ServiceError(message="Redis service is unavailable.")
    return redis


async def get_json(redis: Redis, key: str) -> Optional[Any]:
    """Read-through cache lookup: `None` means a cache miss."""
    raw = await redis.get(key)
    return json.loads(raw) if raw is not None else None


async def set_json(redis: Redis, key: str, value: Any, ttl: int) -> None:
    await redis.set(key, json.dumps(value), ex=ttl)


async def delete_pattern(redis: Redis, pattern: str) -> None:
    """Invalidate every key matching `pattern` (e.g. `"feature_management:list:*"`)."""
    async for key in redis.scan_iter(match=pattern):
        await redis.delete(key)
