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


async def _run(monkeypatch, rules, scores, type="image_generation"):
    """`scores` maps rule name -> score, or a raw string to simulate a broken reply. Returns the calls made."""
    calls = []

    async def fake_settings(ctx):
        return {"prompt_guardrails": rules}

    async def fake_openrouter(self, method, url, user_id, **kwargs):
        schema = kwargs["json"]["response_format"]["json_schema"]["schema"]
        (name,) = schema["properties"]  # each call must carry exactly one dimension
        calls.append(name)
        if isinstance(scores, str):
            return _Resp(scores)
        return _Resp(json.dumps({name: scores[name]}))

    monkeypatch.setattr(vp, "get_admin_settings", fake_settings)
    monkeypatch.setattr(vp.APICaller, "openrouter", fake_openrouter)
    await vp.validate_prompt(None, "a cat", "m", "k", 1, type)  # type: ignore
    return calls


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
@pytest.mark.parametrize(
    "rule,message",
    [
        ("prompt_injection", "prompt_injection_detected"),
        ("nfsw", "prompt_nsfw_detected"),
        ("image_generation", "prompt_not_generation_related"),
    ],
)
async def test_score_above_threshold_raises(monkeypatch, rule, message):
    with pytest.raises(DataValidationError) as e:
        await _run(monkeypatch, _rules(**{rule: 0.5}), {rule: 0.9})
    assert e.value.message == message


@pytest.mark.asyncio
@pytest.mark.parametrize("score", [0.1, 0.5])
async def test_score_at_or_below_threshold_passes(monkeypatch, score):
    rules = _rules(prompt_injection=0.5, nfsw=0.5, image_generation=0.5)
    await _run(monkeypatch, rules, {"prompt_injection": score, "nfsw": score, "image_generation": score})


@pytest.mark.asyncio
async def test_one_call_per_active_rule_and_other_type_ignored(monkeypatch):
    rules = _rules(nfsw=0.5, image_generation=0.5, video_generation=0.5, prompt_injection=0)
    calls = await _run(monkeypatch, rules, {"nfsw": 0, "image_generation": 0})
    assert sorted(calls) == ["image_generation", "nfsw"]


@pytest.mark.asyncio
async def test_missing_score_or_bad_json_fails_closed(monkeypatch):
    for content in ({"nfsw": 0.0}, "not json"):
        with pytest.raises(DataValidationError) as e:
            await _run(
                monkeypatch, _rules(image_generation=0.5), content if isinstance(content, str) else json.dumps(content)
            )
        assert e.value.message == "prompt_ranking_failed"
