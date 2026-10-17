class EmployeesMessage:
    def __init__(self) -> None:
        self.message: dict[str, str] = {
            "employee_resigned": "This employee has resigned.",
            "task_or_song_required": "A task or song is required to check employee assignment.",
        }
