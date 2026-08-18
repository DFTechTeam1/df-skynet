class PreferenceMessage:
    def __init__(self) -> None:
        self.message: dict[str, str] = {
            "preference_already_exists": "Your preferences were already saved by another request. Please try again.",
        }
