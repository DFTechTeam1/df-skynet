class CommonMessage:
    def __init__(self) -> None:
        self.message: dict[str, str] = {
            "data_not_found_error": "Data not found.",
            "data_validation_error": "Data validation error.",
            "data_conflict_error": "This data conflicts with an existing record.",
            "internal_server_error": "Internal Server Error.",
        }
