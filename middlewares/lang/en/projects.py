class ProjectsMessage:
    def __init__(self) -> None:
        self.message: dict[str, str] = {
            "project_song_has_no_entertainment_task_songs": "The song '{name}' doesn't have any entertainment task assigned yet.",
            "production_task_already_completed": "The production task '{name}' has already been completed, so you can no longer add elements to it.",
            "entertainment_task_already_completed": "The entertainment task '{name}' has already been completed, so you can no longer add elements to it.",
        }
