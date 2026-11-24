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
            "chat_queue_unavailable": "Pesan Anda belum dapat dimasukkan ke antrean. Silakan coba beberapa saat lagi.",
            "guardrail_prompt_injection": "Pesan Anda diblokir karena terindikasi mencoba mengubah instruksi sistem.",
            "guardrail_nsfw": "Pesan Anda diblokir karena mengandung konten yang tidak diizinkan.",
            "guardrail_chat_assistant": "Pesan Anda tidak terlihat seperti pertanyaan atau obrolan untuk asisten. Silakan ajukan pertanyaan atau ceritakan apa yang Anda butuhkan.",
            "guardrail_use_case": "Kebutuhan terdeteksi: {use_case}.",
            "guardrail_no_use_case": "Kami belum bisa memahami maksud pesan ini. Silakan ubah kalimatnya.",
            "prompt_guardrail_timeout": "Pemeriksaan pesan Anda memakan waktu terlalu lama. Silakan coba beberapa saat lagi.",
            "prompt_guardrail_provider_error": "Layanan pemeriksaan pesan mengembalikan error. Silakan coba beberapa saat lagi.",
            "prompt_guardrail_unreachable": "Layanan pemeriksaan pesan tidak dapat dihubungi. Silakan coba beberapa saat lagi.",
        }
