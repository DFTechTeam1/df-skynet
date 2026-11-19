class CommonMessage:
    def __init__(self) -> None:
        self.message: dict[str, str] = {
            "too_many_requests": "Too many requests. Please wait a moment before trying again.",
            "success": "Success",
            "data_not_found_error": "We couldn't find what you're looking for.",
            "data_validation_error": "Some of the information you entered isn't valid. Please check and try again.",
            "data_conflict_error": "This conflicts with something that already exists. Please review and try again.",
            "project_action_requires_ongoing": "{action} can only be performed while the project is ongoing.",
            "default_model_not_configured": "The default {model} model hasn't been set up yet. Please ask your administrator to choose one in the settings.",
            "global_project_setting_not_configured": "The global project settings haven't been set up yet. Please ask your administrator to configure them in the settings.",
            "internal_server_error": "Something went wrong on our system. Please try again in a moment.",
        }
