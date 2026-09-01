class ApiKeyManagementMessage:
    def __init__(self) -> None:
        self.message: dict[str, str] = {
            "api_key_not_found": "API key not found.",
            "api_key_already_exists": "An API key with this name already exists.",
            "employee_not_found": "We couldn't find an employee matching this PIC.",
            "employee_already_resigned": "This employee has already resigned and can't be assigned as PIC.",
            "employee_position_not_allowed": "Only a Project Manager or Assistant Project Manager can be assigned as PIC.",
            "employee_already_has_main_api_key": "This employee already has a main API key. Only one main API key is allowed per employee.",
            "cannot_delete_main_api_key": "This key is currently marked as main and can't be deleted. Reassign or update it first.",
            "api_key_missing_hash": "This API key is missing setup information from when it was created, so it can't be updated. It can only be deleted.",
            "api_key_expiry_too_soon": "Expiry date must be at least 7 days from now, so the key survives until it's automatically rotated.",
            "api_key_expiry_must_be_in_future": "Expiry date must be in the future.",
            "openrouter_key_create_failed": "OpenRouter rejected the API key creation. Please try again later.",
            "api_key_employee_deleted": "This key's assigned PIC no longer exists, so it can't be updated. It can only be deleted.",
            "api_key_copy_missing_hash": "This API key is missing setup information from when it was created, so it can't be copied. It can only be deleted.",
            "api_key_copy_missing_employee": "This key's assigned PIC no longer exists, so it can't be copied. It can only be deleted.",
            "api_key_openrouter_sync_failed": "This API key couldn't be updated because it no longer matches what's on OpenRouter. You can still copy or delete it, but it can't be edited.",
            "api_key_expired": "This API key has expired. It can only be deleted — create a new key instead.",
        }
