class CommonMessage:
    def __init__(self) -> None:
        self.message: dict[str, str] = {
            "success": "Success",
            "data_not_found_error": "We couldn't find what you're looking for.",
            "data_validation_error": "Some of the information you entered isn't valid. Please check and try again.",
            "data_conflict_error": "This conflicts with something that already exists. Please review and try again.",
            "internal_server_error": "Something went wrong on our system. Please try again in a moment.",
        }
