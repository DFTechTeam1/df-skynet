import json
from types import SimpleNamespace
import pytest
import services.openrouter_credits as oc
from services.api_caller import APICaller


class _Res:
    def __init__(self, status, body):
        self.is_error, self.content, self._body = status >= 400, b"x", body

    def json(self):
        return self._body


def test_parse_keeps_raw_numbers_and_rejects_errors():
    ok = _Res(200, {"data": {"total_credits": 1550, "total_usage": 1526.2977413219999, "extra": 1}})
    assert oc._parse(ok) == {"total_credits": 1550, "total_usage": 1526.2977413219999}
    assert oc._parse(_Res(502, {"error": {}})) is None


def test_apply_creates_then_updates_single_json_row():
    row = oc._apply(None, {"total_credits": 1, "total_usage": 2})
    assert (row.code, row.key) == ("openrouter_credits", "credits")
    assert json.loads(row.value) == {"total_credits": 1, "total_usage": 2}
    row2 = oc._apply(row, {"total_credits": 5, "total_usage": 3})
    assert row2 is row and json.loads(row.value)["total_credits"] == 5 and row.updated_at is not None


@pytest.mark.asyncio
async def test_logged_openrouter_call_triggers_refresh_and_failure_does_not_break_it(monkeypatch):
    import services.api_caller as ac

    calls = []

    async def boom(db):
        calls.append("refresh")
        raise RuntimeError("down")

    class _Resp:
        content, is_error, status_code = b"{}", False, 200
        headers: dict = {}
        request = SimpleNamespace(url="https://openrouter.ai/api/v1/chat/completions")

        def json(self):
            return {}

    async def fake_call(self, *a, **k):
        return _Resp()

    class _Db:
        def add(self, *a):
            pass

    async def fake_get_db():
        yield _Db()

    async def fake_query(**k):
        return None

    monkeypatch.setattr(ac, "refresh_credits", boom)
    monkeypatch.setattr(ac, "get_db", fake_get_db)
    monkeypatch.setattr(ac, "query", fake_query)
    monkeypatch.setattr(ac, "OPENROUTER_MANAGEMENT_KEY", "k")
    monkeypatch.setattr(APICaller, "call", fake_call)
    caller = APICaller(base_url="https://openrouter.ai/api/v1")
    res = await caller.openrouter("POST", "/chat/completions", user_id=1)
    assert res.status_code == 200 and calls == ["refresh"]
