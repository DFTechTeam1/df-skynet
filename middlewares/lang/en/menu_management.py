class MenuManagementMessage:
    def __init__(self) -> None:
        self.message: dict[str, str] = {
            "menu_not_found": "Menu not found.",
            "menu_already_exists": "A menu with this name already exists.",
            "menu_feature_not_found": "One or more selected features could not be found.",
            "menu_used_by_generations": "This menu has been used by existing generations and cannot be deleted.",
            "menu_delete_forbidden": "You are not allowed to delete this menu.",
        }
