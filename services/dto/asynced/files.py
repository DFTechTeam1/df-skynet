from uuid import UUID
from error import DataNotFoundError
from log import logging
from typing import Any, Optional
from sqlalchemy import or_
from sqlalchemy.orm import selectinload
from services.dto import ConnectionContext
from services.redis import get_json, set_json
from services.dto.asynced.admin_settings import get_folder_depth_limit
from services.mysql import query
from services.mysql.model import DfEngineUploadFiles, Employees, ProjectSongLists, ProjectTasks, Users
from services.mysql.model.df_engine_upload_files import UPLOAD_TYPE_ICON_COLOR
from utils.formatter import format_datetime, format_size, format_udin_url, format_user_employees
from services.dto.format_response import TreeFile
from schemas.format.action import FolderAction, UploadedFileAction
from schemas.format.files import UserUploadedFile
from utils.serializer import serialize


async def get_user_uploaded_files_refactored(
    ctx: ConnectionContext,
    viewer_id: int,
    project_id: Optional[int] = None,
    task_id: Optional[int] = None,
    song_id: Optional[int] = None,
    personal_file: bool = False,
    has_override: bool = False,
    exclude_columns: tuple[str, ...] = ("favourited_at", "archieved_at"),
) -> list[dict[str, Any]]:
    """Return the uploaded files and folders visible for the given scope.

    Results are served from Redis when a cached copy exists for the exact same
    arguments. Otherwise the rows are queried from ``df_engine_upload_files``
    (newest first) and each one is formatted for the frontend. Folder rows get a
    ``FolderAction`` limited by the admin ``folder_depth_limit``; all other rows
    get an ``UploadedFileAction``. The formatted list is then cached.

    Args:
        ctx: Request context holding the DB session, Redis client and cache keys.
        viewer_id: ID of the requesting user. Used by ``personal_file`` and to
            decide ownership in the returned actions.
        project_id: Only return files of this project.
        task_id: Only return files uploaded under this task.
        song_id: Only return files uploaded under this song.
        personal_file: If True, only return files created by ``viewer_id``.
        has_override: Whether the viewer has an override role and may modify
            files or folders they do not own.
        exclude_columns: Field names removed from every returned item. Part of
            the cache key, so different values never share a cached copy.

    Returns:
        A list of JSON-ready dicts, newest first. A file contains ``path``,
        ``url``, ``size``, ``kind``, ``icon``, ``color``, ``task``, ``creator``,
        ``updater``, the timestamps and its action. A folder contains only
        ``name``, ``path``, ``kind``, ``icon``, ``color``, ``creator``,
        ``updater`` and its action. Sizes and timestamps are already
        human-readable (e.g. ``"5.09 MB"``, ``"15 October 2026, 15:36"``).

    Note:
        ``task`` is the task name if the file has a ``task_id``, else the song
        name if it has a ``song_id``, else ``None``. Names are loaded for the
        relation matching the arguments: ``task_id`` only loads the task,
        ``song_id`` only loads the song, anything else loads both.

        The cache key does not include ``depth_limit``, so folder actions may be
        stale until the cached entry expires after an admin changes the limit.
    """
    depth_limit = await get_folder_depth_limit(ctx)
    cache_key = ctx.key.user_uploaded_files_refactored(
        viewer_id, project_id, task_id, song_id, personal_file, has_override, exclude_columns
    )
    data = await get_json(ctx.redis, cache_key)
    if data:
        return data

    filters = []
    if personal_file:
        filters.append(DfEngineUploadFiles.created_by == viewer_id)
    if project_id:
        filters.append(DfEngineUploadFiles.project_id == project_id)
    if task_id:
        filters.append(DfEngineUploadFiles.task_id == task_id)
    if song_id:
        filters.append(DfEngineUploadFiles.song_id == song_id)

    name_options = []
    if task_id or not song_id:
        name_options.append(selectinload(DfEngineUploadFiles.task).load_only(ProjectTasks.uid, ProjectTasks.name))  # type: ignore
    if song_id or not task_id:
        name_options.append(
            selectinload(DfEngineUploadFiles.song).load_only(ProjectSongLists.uid, ProjectSongLists.name)
        )  # type: ignore

    files = await query(
        db=ctx.db,
        table=DfEngineUploadFiles,
        options=(
            selectinload(DfEngineUploadFiles.created_by_user)  # type: ignore
            .load_only(Users.image)  # type: ignore
            .selectinload(Users.employees)  # type: ignore
            .load_only(Employees.nickname),  # type: ignore
            selectinload(DfEngineUploadFiles.updated_by_user)  # type: ignore
            .load_only(Users.image)  # type: ignore
            .selectinload(Users.employees)  # type: ignore
            .load_only(Employees.nickname),  # type: ignore
            *name_options,
        ),
        filters=tuple(filters),
        order_by=(
            DfEngineUploadFiles.created_at.desc(),  # type: ignore
            DfEngineUploadFiles.created_by.desc(),  # type: ignore
        ),
    )

    result = [
        UserUploadedFile(
            file_uid=record["uid"],
            name=record["name"],
            path=record["path"],
            task_uid=(record.get("task") or {}).get("uid"),
            song_uid=(record.get("song") or {}).get("uid"),
            task=(record.get("task") or record.get("song") or {}).get("name"),
            kind=record["type"],
            size=record["size"],
            created_at=record["created_at"],
            updated_at=record["updated_at"],
            creator=format_user_employees(record["created_by_user"]),
            updater=format_user_employees(record["updated_by_user"]),
            action=(
                FolderAction.action(record["created_by"] == viewer_id, has_override, record["path"], depth_limit)
                if record["type"] == "folder"
                else UploadedFileAction.action(record["created_by"] == viewer_id, has_override)
            ),
        ).model_dump(mode="json", exclude=set(exclude_columns))
        for record in serialize(files)
    ]

    await set_json(ctx.redis, cache_key, result)
    return result


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
            selectinload(DfEngineUploadFiles.updated_by_user)  # type: ignore
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
            "updater": format_user_employees(record["updated_by_user"]),
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
        "updater": format_user_employees(record.get("updated_by_user")),
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
            selectinload(DfEngineUploadFiles.updated_by_user)  # type: ignore
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
