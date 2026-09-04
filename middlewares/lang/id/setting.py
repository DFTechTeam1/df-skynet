class SettingMessage:
    def __init__(self) -> None:
        self.message: dict[str, str] = {
            "project_not_found": "Project tidak ditemukan.",
            "model_option_not_found": "Model yang dipilih tidak ditemukan.",
            "project_class_not_found": "Kelas proyek tidak ditemukan.",
            "project_class_limitation_not_found": "Belum ada batasan yang dikonfigurasi untuk kelas proyek ini.",
            "global_setting_not_configured": "Konfigurasikan pengaturan global terlebih dahulu sebelum melihat pengaturan proyek.",
            "project_class_not_assigned": "Proyek ini belum memiliki kelas proyek.",
            "setting_engine_model_must_be_text": "Model enhancer dan assistant harus berupa model teks.",
            "setting_engine_model_must_be_enabled": "Model enhancer dan assistant harus berupa model yang aktif (enabled).",
            "setting_engine_model_must_be_available": "Model enhancer dan assistant harus masih tersedia dari OpenRouter.",
        }
