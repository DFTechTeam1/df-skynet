import json
from uuid import UUID
from functools import lru_cache
from typing import Any, Optional, Literal
from redis.asyncio import Redis
from redis.exceptions import AuthenticationError as RedisAuthError
from apps.secret import REDIS_HOST, REDIS_PASSWORD, REDIS_PORT
from error import AuthenticationError, ServiceError


@lru_cache
def client() -> Redis:
    """Create and return the shared Redis client.

    The Redis client is cached using ``lru_cache`` so that repeated calls
    return the same client instance instead of creating a new connection
    for each request.

    Returns:
        Redis: A configured Redis client using the application Redis
            connection settings.
    """
    return Redis(
        host=REDIS_HOST,
        port=REDIS_PORT,
        password=REDIS_PASSWORD,
    )


async def get_redis() -> Redis:
    """FastAPI dependency that provides a healthy shared Redis client.

    Retrieves the shared Redis client and verifies that the Redis service
    is reachable by sending a ``PING`` command. Redis authentication errors
    and other connection or service errors are converted into application-
    specific exceptions.

    Returns:
        Redis: The shared Redis client after a successful health check.

    Raises:
        AuthenticationError: If Redis authentication fails or the provided
            Redis credentials are invalid.
        ServiceError: If Redis is unavailable or another unexpected error
            occurs while checking the connection.
    """
    redis = client()

    try:
        await redis.ping()
    except RedisAuthError:
        raise AuthenticationError(
            message=("Failed to connect to Redis. Please check your credentials and connection settings.")
        )
    except Exception:
        raise ServiceError(message="Redis service is unavailable.")

    return redis


async def get_json(redis: Redis, key: str) -> Optional[Any]:
    """Retrieve and deserialize a JSON value stored in Redis.

    The value associated with the given key is retrieved from Redis and
    deserialized using ``json.loads()``. If the key does not exist, ``None``
    is returned.

    Args:
        redis: An asynchronous Redis client used to retrieve the value.
        key: The Redis key whose value should be retrieved.

    Returns:
        The deserialized Python value if the key exists, otherwise ``None``.

    Raises:
        json.JSONDecodeError: If the stored value is not valid JSON.
        redis.RedisError: If an error occurs while communicating with Redis.
    """
    raw = await redis.get(key)
    return json.loads(raw) if raw is not None else None


async def set_json(
    redis: Redis,
    key: str,
    value: Any,
    ttl: int = 86400,
) -> None:
    """Serialize a value to JSON and store it in Redis with an expiration time.

    The provided value is serialized using ``json.dumps()`` before being
    stored. If ``ttl`` is specified, the Redis key will automatically expire
    after the given number of seconds.

    Args:
        redis: An asynchronous Redis client used to store the value.
        key: The Redis key under which the serialized value will be stored.
        value: The Python value to serialize and store. The value must be
            JSON-serializable.
        ttl: The time-to-live for the Redis key, in seconds. Defaults to
            86400 seconds (24 hours).

    Returns:
        None.

    Raises:
        TypeError: If ``value`` is not JSON-serializable.
        redis.RedisError: If an error occurs while communicating with Redis.
    """
    await redis.set(key, json.dumps(value), ex=ttl)


async def delete_pattern(redis: Redis, pattern: str) -> None:
    """Delete all Redis keys matching the specified pattern.

    Iterates over matching keys using Redis ``SCAN`` instead of the
    ``KEYS`` command, allowing the operation to be performed without
    blocking the Redis server while scanning large keyspaces.

    Args:
        redis: An asynchronous Redis client used to scan and delete keys.
        pattern: A Redis glob-style pattern used to identify keys to delete.
            For example, ``"feature_management:list:*"`` matches all keys
            starting with ``"feature_management:list:"``.

    Returns:
        None.

    Raises:
        redis.RedisError: If an error occurs while scanning or deleting
            keys in Redis.
    """
    async for key in redis.scan_iter(match=pattern):
        await redis.delete(key)


class CacheKeys:
    def user_preference(self, user_id: int) -> str:
        return f"user_preference:{user_id}"

    def prompt_templates(self, name: Optional[str] = None) -> str:
        return f"prompt_template:list:{(name or '').strip().lower() or 'all'}"

    def prompt_template_detail(self, uid: UUID) -> str:
        return f"prompt_template:detail:{uid}"

    def menu_managements(self, name: Optional[str] = None) -> str:
        return f"menu_management:list:{(name or '').strip().lower() or 'all'}"

    def menu_management_detail(self, uid: UUID) -> str:
        return f"menu_management:detail:{uid}"

    def feature_managements(self, name: Optional[str] = None) -> str:
        return f"feature_management:list:{(name or '').strip().lower() or 'all'}"

    def feature_management_detail(self, uid: UUID) -> str:
        return f"feature_management:detail:{uid}"

    def setting_detail(self, project_uid: Optional[UUID] = None) -> str:
        return f"setting:detail:{project_uid or 'all'}"

    def setting_detail_pattern(self) -> str:
        return "setting:detail:*"

    def setting_logs_pagination(self, page: int, items_per_page: int, search: Optional[str] = None) -> str:
        return f"setting:logs:page={page}:size={items_per_page}:search={(search or '').strip().lower() or 'all'}"

    def setting_logs_pattern(self) -> str:
        return "setting:logs:*"

    def model_pagination_pattern(self) -> str:
        return "model_option:*"

    def setting_global(self) -> str:
        return "setting:global"

    def setting_project(self, uid: UUID) -> str:
        return f"setting:project:{uid}"

    def setting_project_pattern(self) -> str:
        return f"setting:project:*"

    def model_pagination(
        self,
        page: int,
        items_per_page: int,
        search: Optional[str] = None,
        type: Optional[Literal["text", "video", "image"]] = None,
        is_enabled: Optional[bool] = None,
    ) -> str:
        return f"model_option:page={page}:size={items_per_page}:search={(search or '').strip().lower() or 'all'}:type={(type or '').strip().lower() or 'all'}:is_enabled={is_enabled if is_enabled is not None else 'all'}"

    def api_key_management(self) -> str:
        return "api_key_management:list:all"

    def api_key_management_detail(self, uid: UUID) -> str:
        return f"api_key_management:detail:{uid}"

    def api_key_management_logs(self, page: int, items_per_page: int) -> str:
        return f"api_key_management:logs:page={page}:size={items_per_page}"

    def api_key_management_logs_pattern(self) -> str:
        return "api_key_management:logs:*"

    def api_key_management_pattern(self) -> str:
        return "api_key_management:*"
