class ModelManagementMessage:
    def __init__(self) -> None:
        self.message: dict[str, str] = {
            "model_option_not_found": "Model tidak ditemukan.",
            "model_option_must_be_enabled_to_set_main": "Aktifkan model ini terlebih dahulu sebelum menjadikannya utama.",
            "model_option_unavailable_cannot_set_enabled": (
                "Model ini sudah tidak tersedia dari OpenRouter dan status aktifnya tidak dapat diubah."
            ),
            "model_option_unavailable_cannot_set_main": (
                "Model ini sudah tidak tersedia dari OpenRouter dan tidak dapat dijadikan utama."
            ),
        }
