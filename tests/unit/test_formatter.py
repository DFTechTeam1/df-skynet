import pytest
from datetime import datetime
from utils.formatter import format_creator, format_datetime


class TestFormatCreator:
    def test_none_returns_none(self):
        assert format_creator(None) is None

    def test_full_shape(self):
        user = {"image": "pic.png", "employees": {"nickname": "Bastian"}}
        assert format_creator(user) == {"image": "pic.png", "nickname": "Bastian"}

    def test_missing_employees_key_gives_none_nickname(self):
        user = {"image": "pic.png"}
        assert format_creator(user) == {"image": "pic.png", "nickname": None}

    def test_employees_explicitly_none_gives_none_nickname(self):
        user = {"image": None, "employees": None}
        assert format_creator(user) == {"image": None, "nickname": None}


class TestFormatDatetime:
    def test_none_returns_none(self):
        assert format_datetime(None) is None

    def test_datetime_object(self):
        value = datetime(2026, 8, 17, 0, 7)
        assert format_datetime(value) == "17 August 2026, 00:07"

    def test_iso_string_is_parsed_then_formatted(self):
        assert format_datetime("2026-08-17T00:07:39.395134") == "17 August 2026, 00:07"

    def test_malformed_string_raises(self):
        with pytest.raises(ValueError):
            format_datetime("not-a-date")
