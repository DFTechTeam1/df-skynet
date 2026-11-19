class CommonMessage:
    def __init__(self) -> None:
        self.message: dict[str, str] = {
            "too_many_requests": "Terlalu banyak permintaan. Silakan tunggu sebentar sebelum mencoba lagi.",
            "success": "Sukses",
            "data_not_found_error": "Data yang Anda cari tidak ditemukan.",
            "data_validation_error": "Data yang Anda masukkan tidak valid. Silakan periksa kembali.",
            "data_conflict_error": "Data ini bertentangan dengan data yang sudah ada. Silakan periksa kembali.",
            "project_action_requires_ongoing": "{action} hanya dapat dilakukan selama proyek masih berjalan.",
            "default_model_not_configured": "Model {model} bawaan belum diatur. Silakan minta administrator untuk memilihnya di pengaturan.",
            "global_project_setting_not_configured": "Pengaturan global proyek belum diatur. Silakan minta administrator untuk mengaturnya di pengaturan.",
            "internal_server_error": "Terjadi kesalahan pada sistem. Silakan coba beberapa saat lagi.",
        }
