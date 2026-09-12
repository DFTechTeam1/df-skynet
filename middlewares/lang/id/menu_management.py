class MenuManagementMessage:
    def __init__(self) -> None:
        self.message: dict[str, str] = {
            "menu_not_found": "Menu tidak ditemukan.",
            "menu_already_exists": "Menu dengan nama yang sama sudah ada.",
            "menu_type_already_in_use": "Tipe menu ini sudah digunakan oleh menu lain.",
            "menu_feature_not_found": "Satu atau lebih feature yang dipilih tidak ditemukan.",
            "menu_type_not_found": "Tipe menu yang diberikan bukan pilihan yang valid.",
            "menu_type_options_not_configured": "Pilihan tipe menu belum dikonfigurasi.",
        }
