from typing import Any, Optional
from services.mysql import query
from services.mysql.model import Employees
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

    row = await query(ctx.db, Employees, filters=tuple(filters), fetch_one=True)
    if not row:
        raise DataNotFoundError(message="employee_not_found")

    employee = serialize(row)
    await set_json(ctx.redis, employee_key, employee)
    logging.info(f"active employee cache set key={employee_key}")

    if raise_error_when_resigned and employee["status"] == EMPLOYEE_STATUS_RESIGNED:
        raise DataValidationError(message="employee_resigned")

    return employee
