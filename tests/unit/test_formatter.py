import pytest
from datetime import datetime
from utils.formatter import format_user_employees, format_datetime


class TestFormatCreator:
    def test_none_returns_none(self):
        """None input returns None."""
        assert format_user_employees(None) is None

    def test_full_shape(self):
        """Full user dict flattens employees.nickname into a top-level nickname alongside image."""
        user = {"image": "pic.png", "employees": {"nickname": "Bastian"}}
        assert format_user_employees(user) == {"image": "pic.png", "nickname": "Bastian"}

    def test_missing_employees_key_gives_none_nickname(self):
        """Missing employees key still returns image with a None nickname."""
        user = {"image": "pic.png"}
        assert format_user_employees(user) == {"image": "pic.png", "nickname": None}

    def test_employees_explicitly_none_gives_none_nickname(self):
        """employees explicitly set to None also yields a None nickname."""
        user = {"image": None, "employees": None}
        assert format_user_employees(user) == {"image": None, "nickname": None}


class TestFormatDatetime:
    def test_none_returns_none(self):
        """None input returns None."""
        assert format_datetime(None) is None

    def test_datetime_object(self):
        """datetime object is formatted as "day Month year, HH:MM"."""
        value = datetime(2026, 8, 17, 0, 7)
        assert format_datetime(value) == "17 August 2026, 00:07"

    def test_iso_string_is_parsed_then_formatted(self):
        """ISO datetime string is parsed and formatted the same way as a datetime object."""
        assert format_datetime("2026-08-17T00:07:39.395134") == "17 August 2026, 00:07"

    def test_malformed_string_raises(self):
        """Malformed date string raises ValueError."""
        with pytest.raises(ValueError):
            format_datetime("not-a-date")
