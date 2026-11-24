class ProjectsMessage:
    def __init__(self) -> None:
        self.message: dict[str, str] = {
            "project_pic_not_assigned": "Proyek ini belum memiliki penanggung jawab (PIC). Silakan tentukan PIC terlebih dahulu.",
            "project_lead_not_assigned": "Proyek ini belum memiliki project lead. Silakan tentukan satu project lead terlebih dahulu.",
            "project_lead_multiple": "Proyek ini memiliki {total_lead} project lead, padahal harus tepat satu. Silakan sisakan satu project lead saja.",
        }
