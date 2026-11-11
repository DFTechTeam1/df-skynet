class PromptTemplateMessage:
    def __init__(self) -> None:
        self.message: dict[str, str] = {
            "prompt_template_already_exists": "Prompt template dengan nama yang sama sudah ada.",
            "prompt_template_not_found": "Prompt template tidak ditemukan.",
            "prompt_template_in_use": "Prompt template ini masih terhubung dengan sebuah page action dan tidak dapat dihapus. Lepaskan hubungannya terlebih dahulu.",
            "prompt_template_self_reference": "Prompt template tidak dapat mereferensikan dirinya sendiri.",
            "prompt_template_reference_not_in_prompt": "Prompt harus menyebutkan setiap template yang Anda pilih sebagai referensi. Tambahkan referensi yang belum ada ke dalam teks prompt, atau hapus dari daftar referensi.",
        }
