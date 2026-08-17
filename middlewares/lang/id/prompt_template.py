class PromptTemplateMessage:
    def __init__(self) -> None:
        self.message: dict[str, str] = {
            "prompt_template_already_exists": "Prompt template dengan nama yang sama sudah ada.",
            "prompt_template_not_found": "Prompt template tidak ditemukan.",
            "prompt_template_in_use": "Prompt template ini masih terhubung dengan sebuah page action dan tidak dapat dihapus. Lepaskan hubungannya terlebih dahulu.",
        }
