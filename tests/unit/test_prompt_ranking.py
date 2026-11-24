import json
from unittest.mock import AsyncMock
import pytest
from error import DataValidationError
import validations.prompt as vp


def _rules(*types):
    return [{"type": t, "instruction": f"classify {t}"} for t in types]


class _Resp:
    def __init__(self, content):
        self._content = content
        self.status_code = 200
        self.is_error = False

    def json(self):
        return {"choices": [{"message": {"content": self._content}}]}


async def _run(monkeypatch, rules, flags, type="image_generation"):
    """`flags` is a dict of booleans, or a raw string for a broken reply. Returns the guardrail calls made."""
    sent = []

    async def fake_settings(ctx):
        return {"prompt_guardrails": rules}

    async def fake_guardrail(**kwargs):
        sent.append(kwargs)
        return _Resp(flags if isinstance(flags, str) else json.dumps(flags))

    monkeypatch.setattr(vp, "get_admin_settings", fake_settings)
    monkeypatch.setattr(vp, "call_prompt_guardrail", fake_guardrail)
    await vp.validate_prompt(None, "a cat", "m", "k", 1, type)  # type: ignore
    return sent


@pytest.mark.asyncio
async def test_no_rules_skips_call(monkeypatch):
    spy = AsyncMock()

    async def fake_settings(ctx):
        return {"prompt_guardrails": None}

    monkeypatch.setattr(vp, "get_admin_settings", fake_settings)
    monkeypatch.setattr(vp, "call_prompt_guardrail", spy)
    await vp.validate_prompt(None, "a cat", "m", "k", 1, "image_generation")  # type: ignore
    spy.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "rule,flags,message",
    [
        ("prompt_injection", {"prompt_injection": True}, "prompt_injection_detected"),
        ("nfsw", {"nfsw": True}, "prompt_nsfw_detected"),
        ("image_generation", {"image_generation": False}, "prompt_not_generation_related"),
    ],
)
async def test_violation_raises(monkeypatch, rule, flags, message):
    with pytest.raises(DataValidationError) as e:
        await _run(monkeypatch, _rules(rule), flags)
    assert e.value.message == message


@pytest.mark.asyncio
async def test_clean_prompt_passes(monkeypatch):
    flags = {"prompt_injection": False, "nfsw": False, "image_generation": True}
    await _run(monkeypatch, _rules("prompt_injection", "nfsw", "image_generation"), flags)


@pytest.mark.asyncio
async def test_single_call_only_for_risk_and_requested_type(monkeypatch):
    rules = _rules("nfsw", "image_generation", "video_generation")
    sent = await _run(monkeypatch, rules, {"nfsw": False, "image_generation": True})
    assert len(sent) == 1
    messages = sent[0]["messages"]
    assert [m["role"] for m in messages] == ["system", "system", "system", "user"]
    texts = [m["content"][0]["text"] for m in messages]
    assert texts[1:] == ["classify nfsw", "classify image_generation", "a cat"]


@pytest.mark.asyncio
async def test_bad_json_or_non_bool_fails_closed(monkeypatch):
    for content in ("not json", {"nfsw": "maybe"}):
        with pytest.raises(DataValidationError) as e:
            await _run(monkeypatch, _rules("image_generation"), content)
        assert e.value.message == "prompt_ranking_failed"
