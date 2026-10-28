class MenuManagementMessage:
    def __init__(self) -> None:
        self.message: dict[str, str] = {
            "menu_not_found": "Menu tidak ditemukan.",
            "menu_already_exists": "Menu dengan nama yang sama sudah ada.",
            "menu_feature_not_found": "Satu atau lebih feature yang dipilih tidak ditemukan.",
            "menu_used_by_generations": "Menu ini sudah digunakan oleh generation yang ada dan tidak dapat dihapus.",
            "menu_delete_forbidden": "Anda tidak diizinkan menghapus menu ini.",
        }
