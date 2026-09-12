class MenuManagementMessage:
    def __init__(self) -> None:
        self.message: dict[str, str] = {
            "menu_not_found": "Menu not found.",
            "menu_already_exists": "A menu with this name already exists.",
            "menu_type_already_in_use": "This menu type is already used by another menu.",
            "menu_feature_not_found": "One or more selected features could not be found.",
            "menu_type_not_found": "The given menu type is not a valid option.",
            "menu_type_options_not_configured": "Menu type options are not configured yet.",
        }
