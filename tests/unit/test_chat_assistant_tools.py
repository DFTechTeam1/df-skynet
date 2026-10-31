import json
import pytest
from services import chat_assistant as ca


class _Resp:
    status_code = 200

    def __init__(self, message):
        self._message = message

    def raise_for_status(self):
        pass

    def json(self):
        return {"choices": [{"message": self._message}], "usage": {"total_tokens": 5, "cost": 0.25}}


class _Caller:
    def __init__(self, replies):
        self.replies, self.payloads = list(replies), []

    async def openrouter(self, method, url, user_id, **kwargs):
        self.payloads.append(json.loads(json.dumps(kwargs["json"])))
        return _Resp(self.replies.pop(0))


def _tool_call(feature):
    return {
        "role": "assistant",
        "content": None,
        "tool_calls": [
            {
                "id": "c1",
                "type": "function",
                "function": {"name": "get_prompt_template", "arguments": json.dumps({"feature": feature})},
            }
        ],
    }


@pytest.mark.asyncio
async def test_model_fetches_the_template_for_the_case_it_picked(monkeypatch):
    fetched = []

    async def _templates(ctx, feature):
        fetched.append(feature)
        return "TEMPLATE-TEXT"

    monkeypatch.setattr(ca, "get_prompt_templates", _templates)
    caller = _Caller([_tool_call("generate_video"), {"role": "assistant", "content": "final prompt"}])
    answer, usage, status = await ca._complete(
        None, caller, 1, "m", [{"role": "user", "content": "bikin prompt video"}]
    )
    assert answer == "final prompt" and fetched == ["generate_video"] and status == 200
    assert usage == {"total_tokens": 10, "cost": 0.5}  # both calls are billed
    assert caller.payloads[1]["messages"][-1] == {"role": "tool", "tool_call_id": "c1", "content": "TEMPLATE-TEXT"}


@pytest.mark.asyncio
async def test_tools_are_withheld_after_the_round_limit(monkeypatch):
    async def _templates(ctx, feature):
        return "T"

    monkeypatch.setattr(ca, "get_prompt_templates", _templates)
    caller = _Caller([_tool_call("generate_image")] * ca.MAX_TOOL_ROUNDS + [{"role": "assistant", "content": "done"}])
    answer, _, _ = await ca._complete(None, caller, 1, "m", [])
    assert answer == "done"
    assert all("tools" in p for p in caller.payloads[:-1]) and "tools" not in caller.payloads[-1]


@pytest.mark.asyncio
async def test_unknown_case_is_rejected_without_a_query():
    assert "Unknown case" in await ca.get_prompt_templates(None, "generate_anything")
