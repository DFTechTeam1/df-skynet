from typing import Any, Optional
from services.mysql import query
from services.mysql.model import Employees, Users, ProjectTaskPics, EntertainmentTaskSongs
from sqlalchemy.orm import load_only, selectinload
from services.redis import get_json, set_json
from services.dto import ConnectionContext
from log import logging
from error import DataNotFoundError, DataValidationError
from utils.serializer import serialize

EMPLOYEE_STATUS_RESIGNED = 6


async def get_employee(
    ctx: ConnectionContext,
    user_id: Optional[int] = None,
    employee_id: Optional[int] = None,
    raise_error_when_resigned: bool = True,
) -> dict[str, Any]:
    employee_key = ctx.key.active_employee(user_id, employee_id)
    employee = await get_json(ctx.redis, employee_key)
    if employee:
        logging.info(f"active employee cache hit key={employee_key}")
        if raise_error_when_resigned and employee["status"] == EMPLOYEE_STATUS_RESIGNED:
            raise DataValidationError(message="employee_resigned")
        return employee

    filters = []
    if user_id is not None:
        filters.append(Employees.user_id == user_id)
    if employee_id is not None:
        filters.append(Employees.id == employee_id)

    row = await query(
        ctx.db,
        Employees,
        filters=tuple(filters),
        options=(
            load_only(
                Employees.id,  # type: ignore
                Employees.uid,  # type: ignore
                Employees.user_id,  # type: ignore
                Employees.name,  # type: ignore
                Employees.nickname,  # type: ignore
                Employees.email,  # type: ignore
                Employees.avatar,  # type: ignore
                Employees.position_id,  # type: ignore
                Employees.boss_id,  # type: ignore
                Employees.status,  # type: ignore
            ),
            selectinload(Employees.users).load_only(Users.image),  # type: ignore
        ),
        fetch_one=True,
    )
    if not row:
        raise DataNotFoundError(message="employee_not_found")

    employee = serialize(row)
    employee["image"] = (employee.pop("users", None) or {}).get("image")
    await set_json(ctx.redis, employee_key, employee)
    logging.info(f"active employee cache set key={employee_key}")

    if raise_error_when_resigned and employee["status"] == EMPLOYEE_STATUS_RESIGNED:
        raise DataValidationError(message="employee_resigned")

    return employee


async def assigned_to_task(
    ctx: ConnectionContext, employee_id: int, task_id: Optional[int] = None, song_id: Optional[int] = None
) -> None:
    if not task_id and not song_id:
        raise DataValidationError(message="task_or_song_required")

    if task_id:
        table, filters = (
            ProjectTaskPics,
            (
                ProjectTaskPics.project_task_id == task_id,
                ProjectTaskPics.employee_id == employee_id,
            ),
        )
    else:
        table, filters = (
            EntertainmentTaskSongs,
            (
                EntertainmentTaskSongs.project_song_list_id == song_id,
                EntertainmentTaskSongs.employee_id == employee_id,
            ),
        )

    assigned = await query(ctx.db, table, columns=(table.id,), filters=filters, fetch_one=True)
    if assigned is None:
        raise DataNotFoundError(message="employee_not_assigned_task")
