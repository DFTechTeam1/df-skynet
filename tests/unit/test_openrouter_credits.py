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


def _settings_session():
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session
    from sqlalchemy.pool import StaticPool
    from services.mysql.model import DfEngineSettings

    eng = create_engine("sqlite://", poolclass=StaticPool)
    DfEngineSettings.__table__.create(eng)
    return Session(eng)


def test_get_stored_credits_sync_reads_only_the_value_column():
    from sqlalchemy import inspect

    db = _settings_session()
    assert oc.get_stored_credits_sync(db) is None
    row = oc._apply(None, {"total_credits": 7, "total_usage": 1})
    row.id = 1
    db.add(row)
    db.commit()
    assert oc.get_stored_credits_sync(db) == {"total_credits": 7, "total_usage": 1}
    db.expunge_all()
    row = oc.query_sync(db, oc.DfEngineSettings, options=(oc.load_only(oc.DfEngineSettings.value),), fetch_one=True)
    assert "updated_at" in inspect(row).unloaded


@pytest.mark.asyncio
async def test_get_stored_credits_async_uses_query_helper():
    db = _settings_session()
    row = oc._apply(None, {"total_credits": 3, "total_usage": 2})
    row.id = 1
    db.add(row)
    db.commit()

    class _Async:
        async def execute(self, stmt):
            return db.execute(stmt)

    assert await oc.get_stored_credits(_Async()) == {"total_credits": 3, "total_usage": 2}


def test_logged_call_sync_looks_up_employee_nickname_via_query_sync(monkeypatch):
    import services.api_caller as ac

    added = []

    class _Db:
        def add(self, obj):
            added.append(obj)

        def commit(self):
            pass

        def close(self):
            pass

    seen = {}

    def fake_query_sync(db, table, **kw):
        seen.update(kw)
        return SimpleNamespace(nickname="Zola")

    monkeypatch.setattr(ac, "make_sync_session", lambda url: lambda: _Db())
    monkeypatch.setattr(ac, "query_sync", fake_query_sync)
    monkeypatch.setattr(ac, "OPENROUTER_MANAGEMENT_KEY", "")

    class _Resp:
        content = b"{}"
        is_error = False
        status_code = 200
        headers = {}
        request = SimpleNamespace(url="http://x")

        def json(self):
            return {}

    caller = ac.APICaller.__new__(ac.APICaller)
    caller.sync_client = SimpleNamespace(headers={})
    caller.call_sync = lambda *a, **k: _Resp()
    caller._logged_call_sync("udin", "GET", "http://x", False, 5)
    assert added[0].name == "Zola" and len(seen["options"]) == 1
