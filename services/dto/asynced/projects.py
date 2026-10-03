import json
from uuid import UUID
from typing import Optional, Any
from services.redis import get_json, set_json
from sqlalchemy.orm import selectinload
from services.mysql.model import (
    Projects,
    ProjectTasks,
    ProjectTaskPics,
    ProjectPersonInCharges,
    ProjectSongLists,
    EntertainmentTaskSongs,
)
from log import logging
from services.mysql import query
from utils.serializer import serialize
from error import DataNotFoundError
from services.dto import ConnectionContext


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


async def _resolve_project_task_row(
    ctx: ConnectionContext, task_uid: Optional[UUID] = None, task_id: Optional[int] = None
) -> Optional[dict[str, Any]]:
    filters = []
    if task_uid is not None:
        filters.append(ProjectTasks.uid == str(task_uid))
    if task_id is not None:
        filters.append(ProjectTasks.id == task_id)
    if not filters:
        return None

    row = await query(
        ctx.db,
        ProjectTasks,
        filters=tuple(filters),
        options=(selectinload(ProjectTasks.project),),  # type: ignore
        fetch_one=True,
    )
    if not row:
        return None

    task = serialize(row)
    if task["project"]["led_detail"]:
        task["project"]["led_detail"] = json.loads(task["project"]["led_detail"])
    task["is_song"] = False
    return task


async def _resolve_song_task_row(
    ctx: ConnectionContext, song_uid: Optional[UUID] = None, song_id: Optional[int] = None
) -> Optional[dict[str, Any]]:
    filters = []
    if song_uid is not None:
        filters.append(ProjectSongLists.uid == str(song_uid))
    if song_id is not None:
        filters.append(ProjectSongLists.id == song_id)
    if not filters:
        return None

    song = await query(ctx.db, ProjectSongLists, filters=tuple(filters), fetch_one=True)
    if not song:
        return None

    assignment = await query(
        ctx.db,
        EntertainmentTaskSongs,
        filters=(EntertainmentTaskSongs.project_song_list_id == song.id,),
        fetch_one=True,
    )
    project = await get_project(ctx, project_id=song.project_id)

    return {
        "id": song.id,
        "uid": song.uid,
        "project_id": song.project_id,
        "project": project,
        "name": song.name,
        "employee_id": assignment.employee_id if assignment else None,
        "status": assignment.status if assignment else None,
        "time_tracker": json.loads(assignment.time_tracker) if assignment and assignment.time_tracker else None,
        "is_song": True,
    }


async def get_project_task(
    ctx: ConnectionContext,
    task_uid: Optional[UUID] = None,
    task_id: Optional[int] = None,
    song_id: Optional[int] = None,
) -> dict[str, Any]:
    """Resolves either a `project_tasks` or `project_song_lists` row. `task_uid` auto-detects
    between the two (tries project_tasks first); `task_id`/`song_id` resolve directly."""
    task_key = ctx.key.get_project_task(task_uid, task_id, song_id)
    project_task = await get_json(ctx.redis, task_key)
    if project_task:
        logging.info(f"project task cache hit key={task_key}")
        return project_task

    if task_id is not None:
        project_task = await _resolve_project_task_row(ctx, task_id=task_id)
    elif song_id is not None:
        project_task = await _resolve_song_task_row(ctx, song_id=song_id)
    else:
        project_task = await _resolve_project_task_row(ctx, task_uid=task_uid)
        if project_task is None:
            project_task = await _resolve_song_task_row(ctx, song_uid=task_uid)

    if project_task is None:
        logging.warning(f"project task not found task_uid={task_uid} task_id={task_id} song_id={song_id}")
        raise DataNotFoundError(message="project_task_not_found")

    await set_json(ctx.redis, task_key, project_task)
    logging.info(f"project task cache set key={task_key}")
    return project_task


async def get_user_tasks(ctx: ConnectionContext, task_id: int, employee_id: int) -> list[dict[str, Any]]:
    user_tasks_key = ctx.key.get_user_tasks(task_id, employee_id)
    user_tasks = await get_json(ctx.redis, user_tasks_key)
    if user_tasks is not None:
        logging.info(f"user tasks cache hit key={user_tasks_key}")
        return user_tasks

    project_task_pics = await query(
        ctx.db,
        ProjectTaskPics,
        filters=(
            ProjectTaskPics.project_task_id == task_id,
            ProjectTaskPics.employee_id == employee_id,
        ),
    )
    if not project_task_pics:
        raise DataNotFoundError(message="employee_not_assigned_task")

    user_tasks = [serialize(pic) for pic in project_task_pics]
    await set_json(ctx.redis, user_tasks_key, user_tasks)
    logging.info(f"user tasks cache set key={user_tasks_key}")
    return user_tasks


async def get_project_pics(ctx: ConnectionContext, project_id: int) -> list[dict[str, Any]]:
    pics_key = ctx.key.get_project_pics(project_id)
    pics = await get_json(ctx.redis, pics_key)
    if pics is not None:
        logging.info(f"project pics cache hit key={pics_key}")
        return pics

    rows = await query(ctx.db, ProjectPersonInCharges, filters=(ProjectPersonInCharges.project_id == project_id,))
    pics = [serialize(row) for row in rows]
    await set_json(ctx.redis, pics_key, pics)
    logging.info(f"project pics cache set key={pics_key}")
    return pics
