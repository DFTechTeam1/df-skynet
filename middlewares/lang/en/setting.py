class SettingMessage:
    def __init__(self) -> None:
        self.message: dict[str, str] = {
            "setting_engine_model_must_be_text": "The enhancer and assistant model must each be a text model.",
            "setting_engine_model_must_be_enabled": "The enhancer and assistant model must be an enabled model.",
            "setting_engine_model_must_be_available": (
                "The enhancer and assistant model must still be available from OpenRouter."
            ),
        }
