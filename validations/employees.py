from services.mysql import get_db, query
from services.mysql.model import Employees
from error import DataNotFoundError, DataValidationError
from utils.serializer import serialize

EMPLOYEE_STATUS_RESIGNED = 6


async def active_employee(user_id: int) -> dict:
    async for db in get_db():
        employee = await query(
            db=db,
            table=Employees,
            filters=(Employees.user_id == user_id,),
            fetch_one=True,
        )
        if not employee:
            raise DataNotFoundError(message="employee_not_found")

        if employee.status == EMPLOYEE_STATUS_RESIGNED:
            raise DataValidationError(message="employee_resigned")

        return serialize(employee)
    return {}
