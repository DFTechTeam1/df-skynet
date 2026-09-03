from typing import Any, Optional, Type, TypeVar
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from sqlmodel import SQLModel
from services.redis import CacheKeys

SETTING_DETAIL_CACHE_KEY = CacheKeys().setting_detail()
SETTING_LOGS_CACHE_PATTERN = "setting:logs:*"
from services.mysql.model import (
    DfEngineModelOptions,
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
    await redis.delete(SETTING_DETAIL_CACHE_KEY)
    await delete_pattern(redis, SETTING_LOGS_CACHE_PATTERN)


async def clear_openrouter_logs(db_session: AsyncSession) -> None:
    """Deletes every `df_engine_openrouter_logs` row so a log test starts from an
    empty table regardless of what an earlier run (or a real OpenRouter call)
    left behind, and clears the cached logs pages so a later fetch doesn't
    still serve rows this just removed.
    """
    await db_session.execute(delete(DfEngineOpenrouterLogs))
    await db_session.commit()
    await delete_pattern(redis_client(), cache_key.api_key_management_logs_pattern())


async def available_model_rows(db_session: AsyncSession, model_type: str) -> list[DfEngineModelOptions]:
    """Every currently-available row of one usage type — a real OpenRouter
    response would only ever echo models it still has, so the sync tests
    rebuild their fake response from exactly this set (plus/minus the one row
    under test) to avoid mass-disabling real, already-synced data."""
    return (
        (
            await db_session.execute(
                select(DfEngineModelOptions).where(
                    DfEngineModelOptions.type == model_type,  # type: ignore
                    DfEngineModelOptions.is_available.is_(True),  # type: ignore
                )
            )
        )
        .scalars()
        .all()
    )


def openrouter_item_from_row(row: DfEngineModelOptions) -> dict[str, Any]:
    """Reconstruct an OpenRouter-shaped model item from a stored row, so a fake
    sync response can carry the full real catalog for a type without the
    endpoint disabling or rewriting anything real."""
    return {
        "id": row.model_id,
        "name": row.name,
        "created": row.created,
        "description": row.description,
        "architecture": row.architecture,
        "supported_parameters": row.supported_parameters,
        "default_parameters": row.default_parameters,
        "supports_streaming": row.supports_streaming,
        "supported_resolutions": row.supported_resolutions,
        "supported_aspect_ratios": row.supported_aspect_ratios,
        "supported_sizes": row.supported_sizes,
        "supported_durations": row.supported_durations,
        "supported_frame_images": row.supported_frame_images,
        "generate_audio": row.generate_audio,
        "allowed_passthrough_parameters": row.allowed_passthrough_parameters,
        "pricing_skus": row.pricing_skus,
        "pricing": row.pricing,
        "top_provider": row.top_provider,
        "knowledge_cutoff": row.knowledge_cutoff.isoformat() if row.knowledge_cutoff else None,
        "expiration_date": row.expiration_date.isoformat() if row.expiration_date else None,
    }


def find_by_name(items: list[dict[str, Any]], name: str) -> dict[str, Any]:
    return next(t for t in items if t["name"] == name)


def response_names(body: dict[str, Any]) -> list[str]:
    return [t["name"] for t in body["data"]]
