import pytest
from error import DataValidationError
from validations.model import validate_image_parameter


def test_n_greater_than_one_is_allowed():
    validate_image_parameter({"n": 3}, {})


def test_n_zero_or_negative_is_rejected():
    with pytest.raises(DataValidationError):
        validate_image_parameter({"n": 0}, {})


def test_n_non_int_is_rejected():
    with pytest.raises(DataValidationError):
        validate_image_parameter({"n": 1.5}, {})
