import json
from sqlalchemy.orm import attributes
from uuid import UUID
from functools import lru_cache
from typing import Any, Optional, Literal
from redis.asyncio import Redis
from redis import Redis as SyncRedis
from redis.exceptions import AuthenticationError as RedisAuthError
from sqlalchemy import event, select
from apps.secret import REDIS_HOST, REDIS_PASSWORD, REDIS_PORT
from error import AuthenticationError, ServiceError
from log import logging
from services.mysql.model import DfEngineGenerationResults, DfEngineGenerations


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


@lru_cache
def sync_client() -> SyncRedis:
    """Sync counterpart to `client()`, for use from Celery tasks (no event loop)."""
    return SyncRedis(
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


def delete_pattern_sync(redis: SyncRedis, pattern: str) -> None:
    """Sync counterpart to `delete_pattern()`, for use from Celery tasks (no event loop)."""
    for key in redis.scan_iter(match=pattern):
        redis.delete(key)


def get_json_sync(redis: SyncRedis, key: str) -> Optional[Any]:
    """Sync counterpart to `get_json()`, for use from Celery tasks (no event loop)."""
    raw = redis.get(key)
    return json.loads(raw) if raw is not None else None


def set_json_sync(redis: SyncRedis, key: str, value: Any, ttl: int = 86400) -> None:
    """Sync counterpart to `set_json()`, for use from Celery tasks (no event loop)."""
    redis.set(key, json.dumps(value), ex=ttl)


def project_file_patterns(key: "CacheKeys", project_id: Optional[int]) -> list[str]:
    """The project-wide file caches (tree, references picker, user galleries) that any file or generation change stales."""
    return [key.main_generations_project_pattern(project_id), key.user_uploaded_files_project_pattern(project_id)]


def invalidate_project_files_sync(redis: SyncRedis, key: "CacheKeys", project_id: Optional[int]) -> None:
    for pattern in project_file_patterns(key, project_id):
        delete_pattern_sync(redis, pattern)


async def invalidate_project_files(redis: Redis, key: "CacheKeys", project_id: Optional[int]) -> None:
    for pattern in project_file_patterns(key, project_id):
        await delete_pattern(redis, pattern)


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
    # --- user_preference ---
    def user_preference(self, user_id: int) -> str:
        return f"user_preference:{user_id}"

    # --- prompt_templates ---
    def prompt_templates(self, name: Optional[str] = None) -> str:
        return f"prompt_template:list:{(name or '').strip().lower() or 'all'}"

    def prompt_template_detail(self, uid: UUID) -> str:
        return f"prompt_template:detail:{uid}"

    # --- menu_management ---
    def menu_managements(self, name: Optional[str] = None) -> str:
        return f"menu_management:list:{(name or '').strip().lower() or 'all'}"

    def menu_management_detail(self, uid: UUID) -> str:
        return f"menu_management:detail:{uid}"

    # --- feature_management ---
    def feature_managements(self, name: Optional[str] = None) -> str:
        return f"feature_management:list:{(name or '').strip().lower() or 'all'}"

    def feature_management_detail(self, uid: UUID) -> str:
        return f"feature_management:detail:{uid}"

    # --- setting (global + per-project) ---
    def setting_detail(self, project_uid: Optional[UUID] = None) -> str:
        return f"setting:detail:{project_uid or 'all'}"

    def setting_detail_pattern(self) -> str:
        return "setting:detail:*"

    def setting_logs_pagination(self, page: int, items_per_page: int, search: Optional[str] = None) -> str:
        return f"setting:logs:page={page}:size={items_per_page}:search={(search or '').strip().lower() or 'all'}"

    def setting_logs_pattern(self) -> str:
        return "setting:logs:*"

    def setting_global(self) -> str:
        return "setting:global"

    def setting_project(self, project_uid: Optional[UUID] = None, project_id: Optional[int] = None) -> str:
        return f"setting:project:uid={project_uid}:id={project_id}"

    def setting_project_pattern(self) -> str:
        return f"setting:project:*"

    # --- model_management ---
    def model_pagination_pattern(self) -> str:
        return "model_option:*"

    def model_option_details(self, uid: UUID) -> str:
        return f"model_option:detail:uid={uid}"

    def model_pagination(
        self,
        page: int,
        items_per_page: int,
        search: Optional[str] = None,
        type: Optional[Literal["text", "video", "image"]] = None,
        is_enabled: Optional[bool] = None,
        is_deleted: Optional[bool] = None,
    ) -> str:
        return (
            f"model_option:page={page}:size={items_per_page}:search={(search or '').strip().lower() or 'all'}"
            f":type={(type or '').strip().lower() or 'all'}"
            f":is_enabled={is_enabled if is_enabled is not None else 'all'}"
            f":is_deleted={is_deleted if is_deleted is not None else 'all'}"
        )

    # --- api_key_management ---
    def api_key_management(self) -> str:
        return "api_key_management:list:all"

    def api_key_management_detail(self, uid: UUID) -> str:
        return f"api_key_management:detail:{uid}"

    def api_key_management_pattern(self) -> str:
        return "api_key_management:*"

    def api_key_main(self, employee_id: int) -> str:
        return f"api_key_management:main:employee_id={employee_id}"

    # --- api_logs ---
    def api_logs(self, source: str, page: int, items_per_page: int) -> str:
        return f"api_logs:source={source}:page={page}:size={items_per_page}"

    def api_logs_pattern(self) -> str:
        return "api_logs:*"

    # --- files (uploads) ---
    def user_files_pattern(self, task_id: Optional[int] = None, song_id: Optional[int] = None) -> str:
        """Every cached file list (all `my_task` variants) for one task or song."""
        return f"user_files:task_id={task_id}:song_id={song_id}:*"

    def user_uploaded_files_refactored(
        self,
        viewer_id: int,
        project_id: Optional[int] = None,
        task_id: Optional[int] = None,
        song_id: Optional[int] = None,
        personal_file: bool = False,
        has_override: bool = False,
        exclude_columns: tuple[str, ...] = (),
    ):
        return f"user_uploaded_files:viewer_id={viewer_id}:project_id={project_id}:task_id={task_id}:song_id={song_id}:personal_file={personal_file}:has_override={has_override}:exclude_columns={','.join(sorted(exclude_columns))}"

    def user_uploaded_files_project_pattern(self, project_id: Optional[int]) -> str:
        """Every `user_uploaded_files_refactored` entry of one project (all viewers, tasks and flags)."""
        return f"user_uploaded_files:viewer_id=*:project_id={project_id}:*"

    def user_files(
        self, task_id: Optional[int] = None, song_id: Optional[int] = None, user_id: Optional[int] = None
    ) -> str:
        return f"user_files:task_id={task_id}:song_id={song_id}:user_id={user_id}"

    def user_file_detail(self, file_uid: str) -> str:
        return f"user_files:detail:file_uid={file_uid}"

    def uploaded_files(self, file_uids: list[str]) -> str:
        return f"uploaded_files:list:file_uids={file_uids}"

    # --- references_picker ---
    def references_picker(
        self, user_id: int, project_id: int, page: int, items_per_page: int, search: Optional[str] = None
    ) -> str:
        return (
            f"references_picker:user_id={user_id}:project_id={project_id}:page={page}:size={items_per_page}"
            f":search={(search or '').strip().lower() or 'all'}"
        )

    def references_picker_pattern(self, user_id: int) -> str:
        return f"references_picker:user_id={user_id}*"

    def global_references_picker(
        self,
        user_id: int,
        project_name: Optional[str],
        file_name: Optional[str],
        page: int,
        items_per_page: int,
    ) -> str:
        return (
            f"global_references_picker:user_id={user_id}:page={page}:size={items_per_page}"
            f":project_name={(project_name or '').strip().lower() or 'all'}"
            f":file_name={(file_name or '').strip().lower() or 'all'}"
        )

    def global_references_picker_pattern(self, user_id: int) -> str:
        return f"global_references_picker:user_id={user_id}*"

    # --- user_galleries ---
    def user_galleries(
        self, user_id: int, task_id: int, page: int, items_per_page: int, search: Optional[str] = None
    ) -> str:
        return (
            f"user_galleries:user_id={user_id}:task_id={task_id}:page={page}:size={items_per_page}"
            f":search={(search or '').strip().lower() or 'all'}"
        )

    def user_galleries_pattern(self, user_id: int) -> str:
        return f"user_galleries:user_id={user_id}:task_id=*"

    # --- generation_detail ---
    def generation_file_detail(self, user_id: int, file_uid: str) -> str:
        return f"generation_files:detail:user_id={user_id}:file_uid={file_uid}"

    def generation_detail(self, user_id: int, generation_uid: str) -> str:
        return f"generation_detail:user_id={user_id}:generation_uid={generation_uid}"

    def enhancer_detail(self, generation_uid: str) -> str:
        return f"enhancer_detail:generation_uid={generation_uid}"

    def generation_file_detail_pattern(self, user_id: int) -> str:
        return f"generation_files:detail:user_id={user_id}:file_uid=*"

    # --- projects ---
    def get_project(self, project_uid: Optional[UUID] = None, project_id: Optional[int] = None) -> str:
        return f"projects:uid={project_uid}:id={project_id}"

    def get_project_task(
        self, task_uid: Optional[UUID] = None, task_id: Optional[int] = None, song_id: Optional[int] = None
    ) -> str:
        return f"projects:tasks:uid={task_uid}:id={task_id}:song_id={song_id}"

    def get_user_tasks(self, task_id: int, employee_id: int) -> str:
        return f"projects:tasks:pics:task_id={task_id}:employee_id={employee_id}"

    def get_project_pics(self, project_id: int) -> str:
        return f"projects:pics:project_id={project_id}"

    # --- employees ---
    def active_employee(self, user_id: Optional[int] = None, employee_id: Optional[int] = None) -> str:
        return f"employees:active:user_id={user_id}:employee_id={employee_id}"

    # --- menus / features ---
    def get_menu(
        self,
        menu_uid: Optional[UUID] = None,
        feature_uid: Optional[UUID] = None,
        search: Optional[str] = None,
    ) -> str:
        return (
            f"menus:features:menu_uid={menu_uid}:feature_uid={feature_uid}"
            f":search={(search or '').strip().lower() or 'all'}"
        )

    def get_menu_pattern(self) -> str:
        return "menus:features:*"

    # --- generation_files ---
    def main_generations_refactored(
        self,
        viewer_id: int,
        project_id: Optional[int] = None,
        task_id: Optional[int] = None,
        song_id: Optional[int] = None,
        personal_file: bool = False,
        has_override: bool = False,
    ) -> str:
        return (
            f"main_generations:viewer_id={viewer_id}:project_id={project_id}:task_id={task_id}:song_id={song_id}"
            f":personal_file={personal_file}:has_override={has_override}"
        )

    def generation_reupload_lock(self, generation_id: int) -> str:
        return f"generation_reupload_lock:{generation_id}"

    def main_generations_project_pattern(self, project_id: Optional[int]) -> str:
        """Every `main_generations_refactored` entry of one project (all viewers, tasks and flags)."""
        return f"main_generations:viewer_id=*:project_id={project_id}:*"

    def generation_files_main_list(
        self, task_id: Optional[int], user_id: Optional[int] = None, search: Optional[str] = None, song_id=None
    ) -> str:
        # the scope id (task or song) stays first so `generation_files_main_list_pattern(<id>)` clears both kinds
        return (
            f"generation_files:main:task_id={task_id if song_id is None else song_id}:is_song={song_id is not None}"
            f":user_id={user_id}:search={(search or '').strip().lower() or 'all'}"
        )

    def generation_files_main_list_pattern(self, task_id: Optional[int]) -> str:
        return f"generation_files:main:task_id={task_id}:*"

    def generation_files_archived_list(
        self,
        user_id: int,
        project_id: Optional[int] = None,
        task_id: Optional[int] = None,
        song_id: Optional[int] = None,
        search: Optional[str] = None,
    ) -> str:
        return (
            f"generation_files:archived:user_id={user_id}:project_id={project_id}:task_id={task_id}:song_id={song_id}"
            f":search={search}"
        )

    def generation_files_favourited_list(
        self,
        user_id: int,
        project_id: Optional[int] = None,
        task_id: Optional[int] = None,
        song_id: Optional[int] = None,
        search: Optional[str] = None,
    ) -> str:
        return (
            f"generation_files:favourited:user_id={user_id}:project_id={project_id}:task_id={task_id}:song_id={song_id}"
            f":search={search}"
        )

    def generation_files_result_list(
        self,
        user_id: Optional[int] = None,
        task_id: Optional[int] = None,
        song_id: Optional[int] = None,
        file_uids: Optional[list[str]] = None,
    ) -> str:
        return f"generation_files:results:user_id={user_id}:task_id={task_id}:song_id={song_id}:file_uids={file_uids}"

    def generation_files_user_lists_patterns(self, user_id: int) -> list[str]:
        """Every task's result/archived/favourited lists of one viewer."""
        return [f"generation_files:{kind}:user_id={user_id}:*" for kind in ("results", "archived", "favourited")]

    def generation_files_references_picker(
        self,
        type: Literal["uploads", "generations"],
        user_id: int,
        project_id: Optional[int] = None,
        search: Optional[str] = None,
    ) -> str:
        return (
            f"generation_files:references_picker:type={type}:user_id={user_id}:project_id={project_id}"
            f":search={(search or '').strip().lower() or 'all'}"
        )

    def generation_files_references_picker_pattern(self, user_id: int) -> str:
        return f"generation_files:references_picker:type=*:user_id={user_id}:*"

    def generation_files_main_detail(self, file_uid: UUID) -> str:
        return f"generation_files:main:detail:file_uid={file_uid}"

    def generation_files_variant_detail(self, file_uid: UUID) -> str:
        return f"generation_files:variant:detail:file_uid={file_uid}"

    def generation_files_variants_detail(self, file_uid: UUID) -> str:
        return f"generation_files:variants:detail:file_uid={file_uid}"
