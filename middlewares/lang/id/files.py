class FilesMessage:
    def __init__(self) -> None:
        self.message: dict[str, str] = {
            "upload_failed": "Unggah file gagal.",
            "project_task_not_found": "Tugas tidak ditemukan.",
            "task_already_finished": "Anda tidak dapat mengunggah file karena tugas ini sudah selesai.",
            "project_not_ongoing": "File hanya dapat diunggah selama proyek masih berjalan.",
        }
