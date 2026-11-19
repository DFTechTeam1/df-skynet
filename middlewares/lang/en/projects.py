class ProjectsMessage:
    def __init__(self) -> None:
        self.message: dict[str, str] = {
            "project_pic_not_assigned": "This project doesn't have a person in charge yet. Please assign one first.",
            "project_lead_not_assigned": "This project doesn't have a project lead yet. Please assign one first.",
            "project_lead_multiple": "This project has {total_lead} project leads, but it must have exactly one. Please keep only one lead.",
        }
