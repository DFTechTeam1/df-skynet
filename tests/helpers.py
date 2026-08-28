from typing import Any, Optional, Type, TypeVar
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from sqlmodel import SQLModel
from apps.controller.api_key_management import LOGS_CACHE_PATTERN as OPENROUTER_LOGS_CACHE_PATTERN
from apps.controller.setting import DETAIL_CACHE_KEY, LOGS_CACHE_PATTERN
from services.redis import CacheKeys
from services.mysql.model import (
    DfEngineOpenrouterLogs,
    DfEnginePreferences,
    DfEngineSettingLogs,
    DfEngineSettings,
    Users,
)
from services.redis import client as redis_client, delete_pattern
from utils.formatter import format_user_employees
from utils.serializer import serialize

ModelT = TypeVar("ModelT", bound=SQLModel)
cache_key = CacheKeys()


async def create_record(db_session: AsyncSession, model: Type[ModelT], data: dict[str, Any]) -> ModelT:
    record = model(**data)
    db_session.add(record)
    await db_session.commit()
    await db_session.refresh(record)
    return record


async def expected_user(db_session: AsyncSession, user_id: int) -> Optional[dict[str, Any]]:
    user = (
        await db_session.execute(
            select(Users)
            .where(Users.id == int(user_id))  # type: ignore
            .options(selectinload(Users.employees))  # type: ignore
        )
    ).scalar_one()
    return format_user_employees(serialize(user))


async def clear_preference_row(db_session: AsyncSession, user_id: int) -> None:
    row = (
        await db_session.execute(select(DfEnginePreferences).where(DfEnginePreferences.user_id == int(user_id)))  # type: ignore
    ).scalar_one_or_none()
    if row is not None:
        await db_session.delete(row)
        await db_session.commit()
    await redis_client().delete(cache_key.user_preference(int(user_id)))


SETTING_CODE = "admin_setting"


async def clear_setting_state(db_session: AsyncSession) -> None:
    """Deletes every `df_engine_settings` row for the admin-setting group and
    every `df_engine_setting_logs` row, so a setting test starts from "nothing
    saved yet" regardless of what an earlier run left behind. Settings are a
    single global config (not scoped per-user), so there's nothing meaningful
    to snapshot/restore the way the model-management `is_main` tests do for
    real, already-synced model rows.
    """
    await db_session.execute(delete(DfEngineSettings).where(DfEngineSettings.code == SETTING_CODE))  # type: ignore
    await db_session.execute(delete(DfEngineSettingLogs))
    await db_session.commit()
    redis = redis_client()
    await redis.delete(DETAIL_CACHE_KEY)
    await delete_pattern(redis, LOGS_CACHE_PATTERN)


async def clear_openrouter_logs(db_session: AsyncSession) -> None:
    """Deletes every `df_engine_openrouter_logs` row so a log test starts from an
    empty table regardless of what an earlier run (or a real OpenRouter call)
    left behind, and clears the cached logs pages so a later fetch doesn't
    still serve rows this just removed.
    """
    await db_session.execute(delete(DfEngineOpenrouterLogs))
    await db_session.commit()
    await delete_pattern(redis_client(), OPENROUTER_LOGS_CACHE_PATTERN)


def find_by_name(items: list[dict[str, Any]], name: str) -> dict[str, Any]:
    return next(t for t in items if t["name"] == name)


def response_names(body: dict[str, Any]) -> list[str]:
    return [t["name"] for t in body["data"]]
