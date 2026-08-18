class CommonMessage:
    def __init__(self) -> None:
        self.message: dict[str, str] = {
            "data_not_found_error": "Data yang Anda cari tidak ditemukan.",
            "data_validation_error": "Data yang Anda masukkan tidak valid. Silakan periksa kembali.",
            "data_conflict_error": "Data ini bertentangan dengan data yang sudah ada. Silakan periksa kembali.",
            "internal_server_error": "Terjadi kesalahan pada sistem. Silakan coba beberapa saat lagi.",
        }
