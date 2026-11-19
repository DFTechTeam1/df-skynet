from services.tasks.prompt_enhancement import normalize_reference_tags

UID = "11111111-1111-4111-8111-111111111111"


def test_bare_uid_is_wrapped():
    assert normalize_reference_tags(f"a cat {UID} on a sofa", [UID]) == f"a cat <refer to {UID}> on a sofa"


def test_existing_tag_is_not_double_wrapped():
    text = f"a cat <refer to {UID}>"
    assert normalize_reference_tags(text, [UID]) == text


def test_missing_uid_is_appended():
    assert normalize_reference_tags("a cat", [UID]) == f"a cat <refer to {UID}>"
