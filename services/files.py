from typing import Any


class FilesService:
    def map_file_actions(self, files: list[dict[str, Any]], user_id: int) -> list[dict[str, Any]]:
        """Flatten uploaded file rows into API-shaped entries with per-file action flags.

        A file's actions require both: it sits below a recognized `upload/<type>`
        root (protects structural/generated paths from tampering), and it was
        `created_by` the current `user_id` — another user's files are listed but
        every action flag comes back `False`.
        """
        mapped = []
        for file in files:
            path = file["path"]
            folder, _, name = path.rpartition("/")
            actionable = "/upload/images/" in path or "/upload/videos/" in path
            is_owner = file["created_by"] == user_id
            mapped.append(
                {
                    "id": file["id"],
                    "name": name,
                    "folder": folder,
                    "path": path,
                    "size": file["size"],
                    "md5": file.get("md5"),
                    "created_by": file["created_by"],
                    "actions": {
                        "can_rename": actionable and is_owner,
                        "can_delete": actionable and is_owner,
                        "can_choose_to_move": actionable and is_owner,
                    },
                }
            )
        return mapped
