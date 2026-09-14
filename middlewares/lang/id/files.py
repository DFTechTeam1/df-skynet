class FilesMessage:
    def __init__(self) -> None:
        self.message: dict[str, str] = {
            "upload_failed": "Unggah file gagal.",
            "project_task_not_found": "Tugas tidak ditemukan.",
            "task_already_finished": "Anda tidak dapat mengunggah file karena tugas ini sudah selesai.",
            "project_not_ongoing": "File hanya dapat diunggah selama proyek masih berjalan.",
            "folder_not_found": "Folder tidak ditemukan.",
            "file_not_found": "File tidak ditemukan.",
            "folder_action_not_permitted": "Anda tidak memiliki izin untuk mengubah folder ini.",
            "file_action_not_permitted": "Anda tidak memiliki izin untuk mengubah file ini.",
            "folder_depth_exceeded": "Folder hanya dapat bersarang hingga 4 tingkat.",
            "invalid_folder_scope": "Folder hanya dapat dibuat di dalam storage upload atau generated.",
            "folder_create_failed": "Folder gagal dibuat.",
            "folder_delete_failed": "Folder gagal dihapus.",
            "files_delete_failed": "Satu atau lebih file gagal dihapus.",
            "file_rename_failed": "File gagal diubah namanya.",
            "folder_rename_failed": "Folder gagal diubah namanya.",
            "files_move_failed": "Satu atau lebih file gagal dipindahkan.",
            "folders_move_failed": "Satu atau lebih folder gagal dipindahkan.",
        }
