class KeyManagementMessage:
    def __init__(self) -> None:
        self.message: dict[str, str] = {
            "api_key_not_found": "API key tidak ditemukan.",
            "api_key_already_exists": "API key dengan nama yang sama sudah ada.",
            "employee_not_found": "Kami tidak menemukan employee yang cocok dengan PIC ini.",
            "employee_already_resigned": "Employee ini sudah resign dan tidak dapat ditugaskan sebagai PIC.",
            "employee_position_not_allowed": "Hanya Project Manager atau Assistant Project Manager yang dapat ditugaskan sebagai PIC.",
        }
