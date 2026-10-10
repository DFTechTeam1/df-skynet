import json
from unittest.mock import AsyncMock
import pytest
from error import DataValidationError
import validations.prompt as vp


def _rules(**thresholds):
    return [{"type": t, "threshold": v, "instruction": f"score {t}"} for t, v in thresholds.items()]


class _Resp:
    def __init__(self, content):
        self._content = content

    def raise_for_status(self):
        pass

    def json(self):
        return {"choices": [{"message": {"content": self._content}}]}


async def _run(monkeypatch, rules, content, type="image_generation"):
    async def fake_settings(ctx):
        return {"prompt_guardrails": rules}

    async def fake_openrouter(self, method, url, user_id, **kwargs):
        return _Resp(content if isinstance(content, str) else json.dumps(content))

    monkeypatch.setattr(vp, "get_admin_settings", fake_settings)
    monkeypatch.setattr(vp.APICaller, "openrouter", fake_openrouter)
    await vp.validate_prompt(None, "a cat", "m", "k", 1, type)  # type: ignore


@pytest.mark.asyncio
async def test_no_active_rules_skips_call(monkeypatch):
    spy = AsyncMock()

    async def fake_settings(ctx):
        return {"prompt_guardrails": _rules(nfsw=0, image_generation=0)}

    monkeypatch.setattr(vp, "get_admin_settings", fake_settings)
    monkeypatch.setattr(vp.APICaller, "openrouter", spy)
    await vp.validate_prompt(None, "a cat", "m", "k", 1, "image_generation")  # type: ignore
    spy.assert_not_called()


@pytest.mark.asyncio
async def test_injection_rejected(monkeypatch):
    with pytest.raises(DataValidationError) as e:
        await _run(monkeypatch, _rules(prompt_injection=0.5), {"prompt_injection": 0.9})
    assert e.value.message == "prompt_injection_detected"


@pytest.mark.asyncio
async def test_low_relatedness_rejected_and_other_type_ignored(monkeypatch):
    rules = _rules(image_generation=0.5, video_generation=0.5)
    with pytest.raises(DataValidationError) as e:
        await _run(monkeypatch, rules, {"image_generation": 0.2})
    assert e.value.message == "prompt_not_generation_related"
    await _run(monkeypatch, rules, {"image_generation": 0.5})


@pytest.mark.asyncio
async def test_missing_score_or_bad_json_fails_closed(monkeypatch):
    for content in ({"nfsw": 0.0}, "not json"):
        with pytest.raises(DataValidationError) as e:
            await _run(monkeypatch, _rules(image_generation=0.5), content)
        assert e.value.message == "prompt_ranking_failed"
