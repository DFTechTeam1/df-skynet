from uuid import uuid4

from schemas.payload.prompt_template import PromptTemplatePayload


def test_template_references_default_is_empty():
    """template_references defaults to []."""
    assert PromptTemplatePayload(name="a", prompt="p").template_references == []


def test_template_references_are_deduped_in_order():
    """Duplicate UIDs collapse to one, keeping first-seen order."""
    a, b = uuid4(), uuid4()
    payload = PromptTemplatePayload(name="a", prompt=f"{a} {b}", template_references=[a, b, a, b])
    assert payload.template_references == [a, b]


def test_reference_uid_missing_from_prompt_is_rejected():
    """Every referenced UID must appear in the prompt text."""
    import pytest
    from pydantic import ValidationError

    a = uuid4()
    with pytest.raises(ValidationError):
        PromptTemplatePayload(name="a", prompt="p", template_references=[a])
    assert PromptTemplatePayload(name="a", prompt=f"p {a}", template_references=[a])
