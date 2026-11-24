class EmployeesMessage:
    def __init__(self) -> None:
        self.message: dict[str, str] = {
            "employee_resigned": "This employee has resigned.",
            "task_or_song_required": "A task or song is required to check employee assignment.",
            "employee_not_found": "Employee not found. Please make sure the account or PIC is registered as an employee.",
        }
