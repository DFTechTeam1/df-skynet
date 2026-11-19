class EmployeesMessage:
    def __init__(self) -> None:
        self.message: dict[str, str] = {
            "employee_resigned": "Employee ini sudah resign.",
            "task_or_song_required": "Task atau lagu wajib diisi untuk memeriksa penugasan employee.",
            "employee_not_found": "Employee tidak ditemukan. Pastikan akun atau PIC sudah terdaftar sebagai employee.",
        }
