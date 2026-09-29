import json
from uuid import UUID
from typing import Optional, Any
from services.redis import get_json, set_json
from sqlalchemy.orm import selectinload
from services.mysql.model import Projects, ProjectTasks, ProjectTaskPics
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


async def get_project_task(
    ctx: ConnectionContext, task_uid: Optional[UUID] = None, task_id: Optional[int] = None
) -> dict[str, Any]:
    task_key = ctx.key.get_project_task(task_uid, task_id)
    project_task = await get_json(ctx.redis, task_key)
    if project_task:
        logging.info(f"project task cache hit key={task_key}")
        return project_task

    filters = []
    if task_uid is not None:
        filters.append(ProjectTasks.uid == str(task_uid))
    if task_id is not None:
        filters.append(ProjectTasks.id == task_id)

    row = await query(
        ctx.db,
        ProjectTasks,
        filters=tuple(filters),
        options=(selectinload(ProjectTasks.project),),  # type: ignore
        fetch_one=True,
    )
    if not row:
        logging.warning(f"project task not found task_uid={task_uid} task_id={task_id}")
        raise DataNotFoundError(message="project_task_not_found")

    project_task = serialize(row)
    if project_task["project"]["led_detail"]:
        project_task["project"]["led_detail"] = json.loads(project_task["project"]["led_detail"])
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
