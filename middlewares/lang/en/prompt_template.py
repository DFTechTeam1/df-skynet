class PromptTemplateMessage:
    def __init__(self) -> None:
        self.message: dict[str, str] = {
            "prompt_template_already_exists": "A prompt template with this name already exists.",
            "prompt_template_not_found": "Prompt template not found.",
            "prompt_template_in_use": "This prompt template is still mapped to a page action and cannot be deleted. Unmap it first.",
        }
