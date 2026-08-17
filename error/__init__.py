from typing import Any
from fastapi import status


class BaseError(Exception):
    def __init__(
        self,
        status_code: int = status.HTTP_500_INTERNAL_SERVER_ERROR,
        message: str = "internal_server_error",
        error: dict[str, Any] | None = None,
    ):
        self.status_code = status_code
        self.message = message
        self.error = error
        super().__init__(message, error)


class ServiceError(BaseError):
    def __init__(
        self,
        status_code: int = status.HTTP_500_INTERNAL_SERVER_ERROR,
        message: str = "internal_server_error",
        error: dict[str, Any] | None = None,
    ):
        super().__init__(status_code, message, error)


class DataValidationError(BaseError):
    def __init__(
        self,
        status_code: int = status.HTTP_422_UNPROCESSABLE_CONTENT,
        message: str = "data_validation_error",
        error: dict[str, Any] | None = None,
    ):
        super().__init__(status_code, message, error)


class DataNotFoundError(BaseError):
    def __init__(
        self,
        status_code: int = status.HTTP_404_NOT_FOUND,
        message: str = "data_not_found_error",
        error: dict[str, Any] | None = None,
    ):
        super().__init__(status_code, message, error)


class DataConflictError(BaseError):
    def __init__(
        self,
        status_code: int = status.HTTP_409_CONFLICT,
        message: str = "data_conflict_error",
        error: dict[str, Any] | None = None,
    ):
        super().__init__(status_code, message, error)


class AuthenticationError(BaseError):
    def __init__(
        self,
        status_code: int = status.HTTP_401_UNAUTHORIZED,
        message: str = "invalid_credential",
        error: dict[str, Any] | None = None,
    ):
        super().__init__(status_code, message, error)
