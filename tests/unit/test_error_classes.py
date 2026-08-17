import pytest
from fastapi import status
from error import (
    AuthenticationError,
    BaseError,
    DataConflictError,
    DataNotFoundError,
    DataValidationError,
    ServiceError,
)

DEFAULTS = [
    (ServiceError, status.HTTP_500_INTERNAL_SERVER_ERROR, "internal_server_error"),
    (DataValidationError, status.HTTP_422_UNPROCESSABLE_CONTENT, "data_validation_error"),
    (DataNotFoundError, status.HTTP_404_NOT_FOUND, "data_not_found_error"),
    (DataConflictError, status.HTTP_409_CONFLICT, "data_conflict_error"),
    (AuthenticationError, status.HTTP_401_UNAUTHORIZED, "invalid_credential"),
]


@pytest.mark.parametrize("error_cls,expected_status,expected_message", DEFAULTS)
def test_default_status_and_message(error_cls, expected_status, expected_message):
    exc = error_cls()
    assert exc.status_code == expected_status
    assert exc.message == expected_message
    assert exc.error is None
    assert isinstance(exc, BaseError)


@pytest.mark.parametrize("error_cls,_status,_message", DEFAULTS)
def test_explicit_overrides_are_respected(error_cls, _status, _message):
    exc = error_cls(status_code=418, message="custom_message", error={"field": ["bad"]})
    assert exc.status_code == 418
    assert exc.message == "custom_message"
    assert exc.error == {"field": ["bad"]}


def test_base_error_defaults():
    exc = BaseError()
    assert exc.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR
    assert exc.message == "internal_server_error"
    assert exc.error is None
