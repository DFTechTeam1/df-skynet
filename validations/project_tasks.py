from services.mysql import get_db, query
from typing import Any
from utils.serializer import serialize
from sqlalchemy.orm import selectinload
from services.mysql.model import ProjectTasks, ProjectTaskPics
from error import DataNotFoundError, DataValidationError

TASK_STATUS_ONPROCESS = 1
PROJECT_STATUS_ONGOING = 1


async def get_project_task(task_uid: str) -> Any:
    async for db in get_db():
        project_task = await query(
            db=db,
            table=ProjectTasks,
            filters=(ProjectTasks.uid == str(task_uid),),
            options=(selectinload(ProjectTasks.project),),  # type: ignore
            fetch_one=True,
        )
        if not project_task:
            raise DataNotFoundError(message="project_task_not_found")

        # Note: Validation will be enabled later
        # if project_task['status'] != TASK_STATUS_ONPROCESS:
        #     raise DataValidationError(message="project_task_not_onprocess")

        # if project_task['project']['status'] != PROJECT_STATUS_ONGOING:
        #     raise DataValidationError(message="project_not_ongoing")
        return serialize(project_task)


async def assigned_task(task_id: int, employee_id: int) -> list[dict[str, Any]]:
    async for db in get_db():
        project_task_pics = await query(
            db=db,
            table=ProjectTaskPics,
            filters=(
                ProjectTaskPics.project_task_id == task_id,
                ProjectTaskPics.employee_id == employee_id,
            ),
        )
        if not project_task_pics:
            raise DataNotFoundError(message="employee_not_assigned_task")

        return [serialize(pic) for pic in project_task_pics]
    return []
