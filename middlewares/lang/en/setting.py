class SettingMessage:
    def __init__(self) -> None:
        self.message: dict[str, str] = {
            "project_not_found": "Project not found.",
            "project_not_onprocess": "This project must be on process to continue this action.",
            "project_uid_or_project_id_required": "Provide either project_uid or project_id.",
            "model_option_not_found": "The selected model could not be found.",
            "project_class_not_found": "Project class not found.",
            "project_class_limitation_not_found": "No limits are configured for this project's class.",
            "global_setting_not_configured": "Configure the global settings before viewing a project's settings.",
            "admin_setting_not_found": "The required admin settings are not configured yet.",
            "setting_log_not_found": "Setting log not found.",
            "project_setting_not_found": "Project setting not found.",
            "project_class_not_assigned": "This project has no project class assigned yet.",
            "setting_engine_model_must_be_text": "The assistant model must be a text model.",
            "setting_engine_model_must_be_enabled": "The assistant model must be an enabled model.",
            "setting_engine_model_must_be_available": ("The assistant model must still be available from OpenRouter."),
        }
