class PreferenceMessage:
    def __init__(self) -> None:
        self.message: dict[str, str] = {
            "preference_already_exists": "Preferensi Anda sudah tersimpan oleh permintaan lain. Silakan coba lagi.",
        }
