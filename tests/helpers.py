from typing import Any, Optional, Type, TypeVar
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from sqlmodel import SQLModel
from services.redis import CacheKeys

SETTING_CACHE_PATTERNS = ("setting:*", "settings:*")
from services.mysql.model import (
    DfEngineExternalApiCalls,
    DfEngineModelOptions,
    DfEnginePreferences,
    DfEngineProjectSettings,
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
    await db_session.execute(delete(DfEngineProjectSettings))
    await db_session.commit()
    for pattern in SETTING_CACHE_PATTERNS:
        await delete_pattern(redis_client(), pattern)


async def clear_external_api_call_logs(db_session: AsyncSession) -> None:
    """Deletes every `df_engine_external_api_calls` row so a log test starts from an
    empty table regardless of what an earlier run (or a real OpenRouter/udin call)
    left behind, and clears the cached logs pages so a later fetch doesn't
    still serve rows this just removed.
    """
    await db_session.execute(delete(DfEngineExternalApiCalls))
    await db_session.commit()
    await delete_pattern(redis_client(), cache_key.api_logs_pattern())


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


# ---- chat assistant helpers ----
from datetime import datetime  # noqa: E402
from services.mysql.factory.df_engine_chat_assistants import DfEngineChatAssistantsFactory  # noqa: E402
from services.mysql.factory.df_engine_chat_sessions import DfEngineChatSessionsFactory  # noqa: E402


def make_chat_session(ctx, created_by, messages, archieved=False):
    """A chat session on `ctx` (menu/project) holding `messages`: `(role, content[, extra])` tuples where
    `extra` may set `has_generation_prompt` / `will_generate_prompt` / `status_code`. Returns `(session, rows)`."""
    session = DfEngineChatSessionsFactory.create(
        menu_id=ctx.menu_id,
        project_id=ctx.project_id,
        created_by=int(created_by),
        archieved_at=datetime.now() if archieved else None,
    )
    rows = [
        DfEngineChatAssistantsFactory.create(
            session_id=session.id,
            role=role,
            content=content,
            sender="openrouter" if role != "user" else "tester",
            **(extra[0] if extra else {}),
        )
        for role, content, *extra in messages
    ]
    return session, rows


def attach_upload(row, user_id, project_id):
    """Links a new uploaded image to the chat row `row`; returns the upload file."""
    from services.mysql.factory.df_engine_attachments import DfEngineAttachmentsFactory
    from services.mysql.factory.df_engine_chat_references import DfEngineChatReferencesFactory
    from services.mysql.factory.df_engine_upload_files import DfEngineUploadFilesFactory

    file = DfEngineUploadFilesFactory.create(created_by=int(user_id), project_id=project_id)
    attachment = DfEngineAttachmentsFactory.create(sourceable_id=file.id, sourceable_type="DfEngineUploadFiles")
    DfEngineChatReferencesFactory.create(chat_id=row.id, attachment_id=attachment.id)
    return file


async def feature_prompts(db, feature_type):
    """Prompts of the active templates linked to the active feature of `feature_type`, in link order."""
    from sqlalchemy import select
    from services.mysql.model import DfEngineFeaturePromptMappings, DfEngineFeatures, DfEnginePromptTemplates

    rows = await db.execute(
        select(DfEnginePromptTemplates.prompt)  # type: ignore
        .join(DfEngineFeaturePromptMappings, DfEngineFeaturePromptMappings.template_id == DfEnginePromptTemplates.id)  # type: ignore
        .join(DfEngineFeatures, DfEngineFeatures.id == DfEngineFeaturePromptMappings.feature_id)  # type: ignore
        .where(
            DfEngineFeatures.type == feature_type,
            DfEngineFeatures.is_active.is_(True),
            DfEnginePromptTemplates.is_active.is_(True),
        )  # type: ignore
        .order_by(DfEngineFeaturePromptMappings.id)  # type: ignore
    )
    return list(rows.scalars().all())
