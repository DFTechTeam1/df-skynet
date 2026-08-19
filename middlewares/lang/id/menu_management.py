class MenuManagementMessage:
    def __init__(self) -> None:
        self.message: dict[str, str] = {
            "menu_not_found": "Menu tidak ditemukan.",
            "menu_already_exists": "Menu dengan nama yang sama sudah ada.",
            "menu_feature_not_found": "Satu atau lebih feature yang dipilih tidak ditemukan.",
        }
