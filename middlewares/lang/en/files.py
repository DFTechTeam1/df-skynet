class FilesMessage:
    def __init__(self) -> None:
        self.message: dict[str, str] = {
            "upload_failed": "File upload failed.",
            "project_task_not_found": "We couldn't find that task.",
            "task_already_finished": "You cannot upload files because this task has already finished.",
            "project_not_ongoing": "Files can only be uploaded while the project is ongoing.",
        }
