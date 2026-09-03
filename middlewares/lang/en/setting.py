class SettingMessage:
    def __init__(self) -> None:
        self.message: dict[str, str] = {
            "project_not_found": "Project not found.",
            "model_option_not_found": "The selected model could not be found.",
            "project_class_not_found": "Project class not found.",
            "setting_engine_model_must_be_text": "The enhancer and assistant model must each be a text model.",
            "setting_engine_model_must_be_enabled": "The enhancer and assistant model must be an enabled model.",
            "setting_engine_model_must_be_available": (
                "The enhancer and assistant model must still be available from OpenRouter."
            ),
        }
