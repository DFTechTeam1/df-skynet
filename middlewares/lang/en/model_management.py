class ModelManagementMessage:
    def __init__(self) -> None:
        self.message: dict[str, str] = {
            "model_option_not_found": "Model not found.",
            "model_option_must_be_enabled_to_set_main": "Enable this model before setting it as main.",
            "model_option_unavailable_cannot_set_enabled": (
                "This model is no longer available from OpenRouter and its enabled state cannot be changed."
            ),
            "model_option_unavailable_cannot_set_main": (
                "This model is no longer available from OpenRouter and cannot be set as main."
            ),
        }
