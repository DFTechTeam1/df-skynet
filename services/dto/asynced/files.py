from uuid import UUID
from error import DataNotFoundError
from log import logging
from typing import Any, Optional
from sqlalchemy.orm import selectinload
from services.dto import ConnectionContext
from services.redis import get_json, set_json
from services.mysql import query
from services.mysql.model import DfEngineUploadFiles, Employees, Users
from services.mysql.model.df_engine_upload_files import UPLOAD_TYPE_ICON_COLOR
from utils.formatter import format_datetime, format_size, format_udin_url, format_user_employees
from utils.serializer import serialize


async def get_user_uploaded_files(
    ctx: ConnectionContext, task_id: Optional[int] = None, song_id: Optional[int] = None, user_id: Optional[int] = None
) -> list[dict[str, Any]]:
    cache_key = ctx.key.user_files(task_id, song_id, user_id)
    data = await get_json(ctx.redis, cache_key)
    if data:
        return data

    files_filters = []
    if song_id is not None:
        files_filters.append(DfEngineUploadFiles.song_id == song_id)
    if task_id is not None:
        files_filters.append(DfEngineUploadFiles.task_id == task_id)
    if user_id is not None:
        files_filters.append(DfEngineUploadFiles.created_by == user_id)  # type: ignore

    files = await query(
        db=ctx.db,
        table=DfEngineUploadFiles,
        options=(
            selectinload(DfEngineUploadFiles.created_by_user)  # type: ignore
            .load_only(Users.image)  # type: ignore
            .selectinload(Users.employees)  # type: ignore
            .load_only(Employees.nickname),  # type: ignore
        ),
        filters=tuple(files_filters),
        order_by=(
            DfEngineUploadFiles.created_at.desc(),  # type: ignore
            DfEngineUploadFiles.created_by.desc(),  # type: ignore
        ),
    )

    result = [
        {
            "file_uid": record["uid"],
            "name": record["name"],
            "type": record["type"],
            "icon": UPLOAD_TYPE_ICON_COLOR.get(record["type"], {}).get("icon"),
            "color": UPLOAD_TYPE_ICON_COLOR.get(record["type"], {}).get("color"),
            "path": record["path"],
            "url": format_udin_url(record["path"]),
            "size": format_size(record["size"]),
            "created_at": format_datetime(record["created_at"]),
            "creator": format_user_employees(record["created_by_user"]),
        }
        for record in serialize(files)
    ]

    await set_json(ctx.redis, cache_key, result)
    logging.info(f"task_id={task_id} user_id={user_id} listed upload files source=db count={len(result)}")
    return result


def _format_upload_file(record: dict[str, Any]) -> dict[str, Any]:
    return {
        "file_uid": record["uid"],
        "name": record["name"],
        "type": record["type"],
        "icon": UPLOAD_TYPE_ICON_COLOR.get(record["type"], {}).get("icon"),
        "color": UPLOAD_TYPE_ICON_COLOR.get(record["type"], {}).get("color"),
        "path": record["path"],
        "url": format_udin_url(record["path"]),
        "size": format_size(record["size"]),
        "created_at": format_datetime(record["created_at"]),
        "creator": format_user_employees(record["created_by_user"]),
    }


async def get_user_uploaded_file(ctx: ConnectionContext, file_uid: UUID) -> dict[str, Any]:
    cache_key = ctx.key.user_file_detail(str(file_uid))
    data = await get_json(ctx.redis, cache_key)
    if data:
        logging.info(f"file_uid={file_uid} fetched upload file source=cache")
        return data

    record = await query(
        db=ctx.db,
        table=DfEngineUploadFiles,
        options=(
            selectinload(DfEngineUploadFiles.created_by_user)  # type: ignore
            .load_only(Users.image)  # type: ignore
            .selectinload(Users.employees)  # type: ignore
            .load_only(Employees.nickname),  # type: ignore
        ),
        filters=(DfEngineUploadFiles.uid == str(file_uid),),
        fetch_one=True,
    )
    if record is None:
        logging.warning(f"file_uid={file_uid} upload file not found")
        raise DataNotFoundError(message="file_not_found")

    result = _format_upload_file(serialize(record))
    await set_json(ctx.redis, cache_key, result)
    logging.info(f"file_uid={file_uid} fetched upload file source=db")
    return result
