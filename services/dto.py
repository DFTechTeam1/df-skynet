import json
from uuid import UUID
from typing import Optional, Any
from sqlalchemy.ext.asyncio import AsyncSession
from redis.asyncio import Redis
from redis import Redis as SyncRedis
from dataclasses import dataclass
from services.redis import CacheKeys, get_json, set_json
from sqlalchemy.orm import selectinload
from services.mysql.model import Projects, DfEngineGenerations, DfEngineGenerationResults
from services.mysql.model.df_engine_generations import GENERATION_KIND_ICON_COLOR
from log import logging
from services.mysql import query
from utils.serializer import serialize
from utils.formatter import format_size, format_datetime, format_udin_url
from error import DataNotFoundError


@dataclass
class ConnectionContext:
    db: AsyncSession
    redis: Redis
    key: CacheKeys


async def get_project(
    ctx: ConnectionContext, project_uid: Optional[UUID] = None, project_id: Optional[int] = None
) -> dict[str, Any]:
    project_key = ctx.key.get_project(project_uid, project_id)
    project = await get_json(ctx.redis, project_key)
    if project:
        logging.info(f"project cache hit key={project_key}")
        return project

    filters = []
    if project_uid is not None:
        filters.append(Projects.uid == str(project_uid))
    if project_id is not None:
        filters.append(Projects.id == project_id)

    row = await query(ctx.db, Projects, filters=tuple(filters), fetch_one=True)
    if not row:
        logging.warning(f"project not found project_uid={project_uid} project_id={project_id}")
        raise DataNotFoundError(message="project_not_found")

    project = serialize(row)
    if project.get("led_detail"):
        project["led_detail"] = json.loads(project["led_detail"])
    await set_json(ctx.redis, project_key, project)
    logging.info(f"project cache set key={project_key}")
    return project


async def get_archieved_files(ctx: ConnectionContext, project_id: int, user_id: int) -> list[dict[str, Any]]:
    archived_key = ctx.key.archived_generations(user_id, project_id)
    data = await get_json(ctx.redis, archived_key)
    if data:
        logging.info(f"archived generations cache hit key={archived_key}")
        return data

    generations = await query(
        ctx.db,
        DfEngineGenerations,
        options=(
            selectinload(
                DfEngineGenerations.result.and_(DfEngineGenerationResults.archieved_at.is_not(None))  # type: ignore
            ),
        ),
        filters=(
            DfEngineGenerations.project_id == project_id,
            DfEngineGenerations.created_by == user_id,
            DfEngineGenerations.result.has(DfEngineGenerationResults.archieved_at.is_not(None)),  # type: ignore
        ),
    )

    archieved_files = sorted(
        (
            {
                "kind": record["kind"],
                "file_uid": record["result"]["uid"],
                "name": record["result"]["name"],
                "is_main": record["result"]["is_main"],
                "is_favourite": record["result"]["is_favourite"],
                "path": format_udin_url(record["result"]["path"]),
                "size": format_size(record["result"]["size"]),
                "version": record["result"]["version"],
                "created_at": format_datetime(record["result"]["created_at"]),
                "archieved_at": record["result"]["archieved_at"],
                "icon": GENERATION_KIND_ICON_COLOR.get(record["kind"], {}).get("icon"),
                "color": GENERATION_KIND_ICON_COLOR.get(record["kind"], {}).get("color"),
                "action": {
                    "can_unarchieve": True,
                    "can_set_main": record["result"]["is_main"] is False,
                    "can_favorited": record["result"]["is_favourite"] is False,
                    "can_unfavorited": record["result"]["is_favourite"] is True,
                    "can_download": True,
                    "can_fetch_detail": True,
                },
            }
            for record in serialize(generations)
        ),
        key=lambda r: r["archieved_at"],
        reverse=True,
    )
    for record in archieved_files:
        record["archieved_at"] = format_datetime(record["archieved_at"])

    await set_json(ctx.redis, archived_key, archieved_files)
    logging.info(f"archived generations cache set key={archived_key} count={len(archieved_files)}")
    return archieved_files


async def get_favourited_files(ctx: ConnectionContext, project_id: int, user_id: int) -> list[dict[str, Any]]:
    favourited_key = ctx.key.favourited_generations(user_id, project_id)
    data = await get_json(ctx.redis, favourited_key)
    if data is not None:
        logging.info(f"favourited generations cache hit key={favourited_key}")
        return data

    generations = await query(
        ctx.db,
        DfEngineGenerations,
        options=(
            selectinload(
                DfEngineGenerations.result.and_(DfEngineGenerationResults.is_favourite.is_(True))  # type: ignore
            ),
        ),
        filters=(
            DfEngineGenerations.project_id == project_id,
            DfEngineGenerations.created_by == user_id,
            DfEngineGenerations.result.has(DfEngineGenerationResults.is_favourite.is_(True)),  # type: ignore
        ),
    )

    favourited_files = sorted(
        (
            {
                "kind": record["kind"],
                "file_uid": record["result"]["uid"],
                "name": record["result"]["name"],
                "is_main": record["result"]["is_main"],
                "is_favourite": record["result"]["is_favourite"],
                "path": format_udin_url(record["result"]["path"]),
                "size": format_size(record["result"]["size"]),
                "version": record["result"]["version"],
                "created_at": record["result"]["created_at"],
                "archieved_at": format_datetime(record["result"]["archieved_at"]),
                "icon": GENERATION_KIND_ICON_COLOR.get(record["kind"], {}).get("icon"),
                "color": GENERATION_KIND_ICON_COLOR.get(record["kind"], {}).get("color"),
                "action": {
                    "can_archieve": record["result"]["archieved_at"] is None,
                    "can_unarchieve": record["result"]["archieved_at"] is not None,
                    "can_set_main": record["result"]["is_main"] is False,
                    "can_unfavorited": True,
                    "can_download": True,
                    "can_fetch_detail": True,
                },
            }
            for record in serialize(generations)
        ),
        key=lambda r: r["created_at"],
        reverse=True,
    )
    for record in favourited_files:
        record["created_at"] = format_datetime(record["created_at"])

    await set_json(ctx.redis, favourited_key, favourited_files)
    logging.info(f"favourited generations cache set key={favourited_key} count={len(favourited_files)}")
    return favourited_files
