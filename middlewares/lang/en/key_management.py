class KeyManagementMessage:
    def __init__(self) -> None:
        self.message: dict[str, str] = {
            "api_key_not_found": "API key not found.",
            "api_key_already_exists": "An API key with this name already exists.",
            "employee_not_found": "We couldn't find an employee matching this PIC.",
            "employee_already_resigned": "This employee has already resigned and can't be assigned as PIC.",
            "employee_position_not_allowed": "Only a Project Manager or Assistant Project Manager can be assigned as PIC.",
            "employee_already_has_main_api_key": "This employee already has a main API key. Only one main API key is allowed per employee.",
            "cannot_delete_main_api_key": "This key is currently marked as main and can't be deleted. Reassign or update it first.",
            "api_key_missing_hash": "This API key has no OpenRouter hash on record, so it can't be managed remotely.",
        }
