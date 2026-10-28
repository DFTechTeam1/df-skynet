class FeatureManagementMessage:
    def __init__(self) -> None:
        self.message: dict[str, str] = {
            "feature_not_found": "Feature tidak ditemukan.",
            "feature_already_exists": "Feature dengan nama yang sama sudah ada.",
            "feature_template_not_found": "Satu atau lebih prompt template yang dipilih tidak ditemukan.",
            "feature_linked_to_menu": "Feature ini masih terhubung dengan sebuah menu dan tidak dapat dihapus. Lepaskan hubungannya di menu management terlebih dahulu.",
            "feature_used_by_generations": "Feature ini sudah digunakan oleh generation yang ada dan tidak dapat dihapus.",
            "feature_linked_to_menu_and_generations": "Feature ini masih terhubung dengan sebuah menu dan sudah digunakan oleh generation yang ada, sehingga tidak dapat dihapus.",
            "feature_delete_forbidden": "Anda tidak diizinkan menghapus feature ini.",
        }
