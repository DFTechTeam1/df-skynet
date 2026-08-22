class ApiKeyManagementMessage:
    def __init__(self) -> None:
        self.message: dict[str, str] = {
            "api_key_not_found": "API key tidak ditemukan.",
            "api_key_already_exists": "API key dengan nama yang sama sudah ada.",
            "employee_not_found": "Kami tidak menemukan employee yang cocok dengan PIC ini.",
            "employee_already_resigned": "Employee ini sudah resign dan tidak dapat ditugaskan sebagai PIC.",
            "employee_position_not_allowed": "Hanya Project Manager atau Assistant Project Manager yang dapat ditugaskan sebagai PIC.",
            "employee_already_has_main_api_key": "Employee ini sudah memiliki main API key. Hanya satu main API key yang diperbolehkan per employee.",
            "cannot_delete_main_api_key": "Key ini sedang ditandai sebagai main dan tidak dapat dihapus. Ubah statusnya terlebih dahulu.",
            "api_key_missing_hash": "API key ini kehilangan informasi setup dari saat pembuatannya, sehingga tidak dapat diupdate. Key ini hanya dapat dihapus.",
            "api_key_expiry_too_soon": "Tanggal expired minimal 7 hari dari sekarang, agar key tetap berlaku hingga dirotasi secara otomatis.",
            "api_key_employee_deleted": "PIC yang ditugaskan pada key ini sudah tidak ada, sehingga tidak dapat diupdate. Key ini hanya dapat dihapus.",
            "api_key_copy_missing_hash": "API key ini kehilangan informasi setup dari saat pembuatannya, sehingga tidak dapat disalin. Key ini hanya dapat dihapus.",
            "api_key_copy_missing_employee": "PIC yang ditugaskan pada key ini sudah tidak ada, sehingga tidak dapat disalin. Key ini hanya dapat dihapus.",
            "api_key_openrouter_sync_failed": "API key ini tidak dapat diupdate karena sudah tidak sesuai dengan data di OpenRouter. Key ini masih dapat disalin atau dihapus, namun tidak dapat diedit.",
        }
