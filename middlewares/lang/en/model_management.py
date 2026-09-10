class ModelManagementMessage:
    def __init__(self) -> None:
        self.message: dict[str, str] = {
            "model_option_not_found": "Model not found.",
            "model_option_must_be_enabled_to_set_main": "Enable this model before setting it as main.",
            "model_option_main_cannot_be_disabled": (
                "The main model cannot be disabled. Set another model as main first."
            ),
            "model_option_unavailable_cannot_set_enabled": (
                "This model is no longer available from OpenRouter and its enabled state cannot be changed."
            ),
            "model_option_unavailable_cannot_set_main": (
                "This model is no longer available from OpenRouter and cannot be set as main."
            ),
            "model_option_already_deleted": "This model is already deleted.",
            "model_option_not_deleted": "This model is not deleted, so it cannot be recovered.",
            "model_option_active_cannot_be_deleted": ("An enabled model cannot be deleted. Disable it first."),
            "model_option_main_cannot_be_deleted": (
                "The main model cannot be deleted. Set another model as main first."
            ),
            "model_option_unavailable_cannot_be_deleted": (
                "A model that is no longer available from OpenRouter cannot be deleted."
            ),
            "openrouter_model_fetch_failed": (
                "Failed to fetch the model list from OpenRouter. Please try again later."
            ),
        }
