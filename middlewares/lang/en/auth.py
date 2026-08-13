class AuthMessage:
    def __init__(self) -> None:
        self.message: dict[str, str] = {
            "invalid_credential": "The credential provided does not match our database."
        }
