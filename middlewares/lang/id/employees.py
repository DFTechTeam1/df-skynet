class EmployeesMessage:
    def __init__(self) -> None:
        self.message: dict[str, str] = {
            "employee_resigned": "Employee ini sudah resign.",
            "task_or_song_required": "Task atau lagu wajib diisi untuk memeriksa penugasan employee.",
        }
