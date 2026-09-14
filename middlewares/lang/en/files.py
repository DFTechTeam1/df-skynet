class FilesMessage:
    def __init__(self) -> None:
        self.message: dict[str, str] = {
            "upload_failed": "File upload failed.",
            "project_task_not_found": "We couldn't find that task.",
            "task_already_finished": "You cannot upload files because this task has already finished.",
            "project_not_ongoing": "Files can only be uploaded while the project is ongoing.",
            "folder_not_found": "We couldn't find that folder.",
            "file_not_found": "We couldn't find that file.",
            "folder_action_not_permitted": "You don't have permission to modify this folder.",
            "file_action_not_permitted": "You don't have permission to modify this file.",
            "folder_depth_exceeded": "Folders can only be nested 4 levels deep.",
            "invalid_folder_scope": "Folders can only be created inside upload or generated storage.",
            "folder_create_failed": "Folder could not be created.",
            "folder_delete_failed": "Folder could not be deleted.",
            "files_delete_failed": "One or more files could not be deleted.",
            "file_rename_failed": "File could not be renamed.",
            "folder_rename_failed": "Folder could not be renamed.",
            "files_move_failed": "One or more files could not be moved.",
            "folders_move_failed": "One or more folders could not be moved.",
        }
