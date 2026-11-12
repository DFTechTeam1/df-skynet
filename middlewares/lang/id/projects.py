class ProjectsMessage:
    def __init__(self) -> None:
        self.message: dict[str, str] = {
            "project_song_has_no_entertainment_task_songs": "Lagu '{name}' belum memiliki entertainment task yang ditugaskan.",
            "production_task_already_completed": "Tugas production '{name}' sudah selesai, sehingga elemen tidak dapat ditambahkan lagi.",
            "entertainment_task_already_completed": "Tugas entertainment '{name}' sudah selesai, sehingga elemen tidak dapat ditambahkan lagi.",
        }
