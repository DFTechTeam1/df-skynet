import pytest
from middlewares.lang import MESSAGES, resolve_message


@pytest.mark.parametrize("key", sorted(MESSAGES["en"].keys()))
@pytest.mark.parametrize("lang", ["en", "id"])
def test_every_known_key_resolves_to_a_localized_string(key, lang):
    """Every known message key resolves to its exact localized string for both en and id."""
    resolved = resolve_message(key, lang)
    assert isinstance(resolved, str)
    assert resolved != ""
    assert resolved == MESSAGES[lang][key]


def test_unsupported_language_falls_back_to_english():
    """Unsupported language code falls back to the English message."""
    key = next(iter(MESSAGES["en"]))
    assert resolve_message(key, "fr") == MESSAGES["en"][key]


def test_unknown_key_returns_the_raw_key():
    """Unknown message key returns the key itself unchanged."""
    assert resolve_message("this_key_does_not_exist") == "this_key_does_not_exist"


def test_unknown_key_with_unsupported_language_still_returns_raw_key():
    """Unknown key combined with an unsupported language still returns the raw key."""
    assert resolve_message("this_key_does_not_exist", "fr") == "this_key_does_not_exist"


def test_default_language_is_english():
    """Omitting the language argument defaults to English."""
    key = next(iter(MESSAGES["en"]))
    assert resolve_message(key) == MESSAGES["en"][key]
