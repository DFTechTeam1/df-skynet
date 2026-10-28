import pytest
from httpx import Response
from error import DataValidationError
from validations.prompt import enhance_prompt


def _patch_openrouter(monkeypatch, response: Response) -> None:
    async def fake_openrouter(self, method, url, user_id, **kwargs):
        return response

    async def fake_close(self):
        return None

    monkeypatch.setattr("services.api_caller.APICaller.openrouter", fake_openrouter)
    monkeypatch.setattr("services.api_caller.APICaller.close", fake_close)


@pytest.mark.asyncio
async def test_native_provider_message_takes_priority(monkeypatch):
    """The provider's own error.message should surface verbatim, not the generic lang key."""
    native_message = "mistralai/codestral-2508:batch cannot be used with the chat/completions endpoint."
    _patch_openrouter(monkeypatch, Response(404, json={"error": {"message": native_message, "code": 404}}))

    with pytest.raises(DataValidationError) as exc_info:
        await enhance_prompt("prompt", "mistralai/codestral-2508:batch", "key", user_id=1)
    assert exc_info.value.message == native_message


@pytest.mark.asyncio
async def test_falls_back_to_lang_key_when_native_message_missing(monkeypatch):
    """No error.message in the provider body (or no body at all) falls back to our own lang key."""
    _patch_openrouter(monkeypatch, Response(500, json={"error": {}}))

    with pytest.raises(DataValidationError) as exc_info:
        await enhance_prompt("prompt", "some/model", "key", user_id=1)
    assert exc_info.value.message == "prompt_enhance_failed"
