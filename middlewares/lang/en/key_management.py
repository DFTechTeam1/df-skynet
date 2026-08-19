class KeyManagementMessage:
    def __init__(self) -> None:
        self.message: dict[str, str] = {
            "api_key_not_found": "API key not found.",
            "api_key_already_exists": "An API key with this name already exists.",
            "employee_not_found": "We couldn't find an employee matching this PIC.",
            "employee_already_resigned": "This employee has already resigned and can't be assigned as PIC.",
            "employee_position_not_allowed": "Only a Project Manager or Assistant Project Manager can be assigned as PIC.",
        }
