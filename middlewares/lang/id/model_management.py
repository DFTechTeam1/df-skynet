class ModelManagementMessage:
    def __init__(self) -> None:
        self.message: dict[str, str] = {
            "model_option_not_found": "Model tidak ditemukan.",
            "model_option_must_be_enabled_to_set_main": "Aktifkan model ini terlebih dahulu sebelum menjadikannya utama.",
            "model_option_main_cannot_be_disabled": (
                "Model utama tidak dapat dinonaktifkan. Jadikan model lain sebagai utama terlebih dahulu."
            ),
            "model_option_unavailable_cannot_set_enabled": (
                "Model ini sudah tidak tersedia dari OpenRouter dan status aktifnya tidak dapat diubah."
            ),
            "model_option_unavailable_cannot_set_main": (
                "Model ini sudah tidak tersedia dari OpenRouter dan tidak dapat dijadikan utama."
            ),
            "model_option_already_deleted": "Model ini sudah dihapus.",
            "model_option_not_deleted": "Model ini tidak dalam keadaan terhapus, sehingga tidak dapat dipulihkan.",
            "model_option_active_cannot_be_deleted": (
                "Model yang aktif tidak dapat dihapus. Nonaktifkan terlebih dahulu."
            ),
            "model_option_main_cannot_be_deleted": (
                "Model utama tidak dapat dihapus. Jadikan model lain sebagai utama terlebih dahulu."
            ),
            "model_option_unavailable_cannot_be_deleted": (
                "Model yang sudah tidak tersedia dari OpenRouter tidak dapat dihapus."
            ),
            "openrouter_model_fetch_failed": ("Gagal mengambil daftar model dari OpenRouter. Silakan coba lagi nanti."),
        }
