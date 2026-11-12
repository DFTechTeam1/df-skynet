import services.pusher as pusher

CHANNEL = "user-generation-project-proj-uid-task-task-uid"


def _stub(monkeypatch):
    calls = []
    monkeypatch.setattr(pusher, "get_pusher", lambda: type("Stub", (), {"trigger": lambda self, *a: calls.append(a)})())
    return calls


def test_failed_status_sends_task_channel_payload_and_token_update(monkeypatch):
    calls = _stub(monkeypatch)
    monkeypatch.setattr(pusher, "_remain", lambda: 6.52)
    pusher.broadcast_generation_status("proj-uid", "task-uid", 7, "abc-uid", "failed", error="boom")
    assert calls == [
        (CHANNEL, "generation-status", {"s": "failed", "e": "boom", "gid": "abc-uid", "u": 7}),
        ("remaining-token", "token-update", {"remain": 6.52}),
    ]


def test_non_final_status_skips_token_update(monkeypatch):
    calls = _stub(monkeypatch)
    pusher.broadcast_generation_status("proj-uid", "task-uid", 7, "abc-uid", "processing")
    assert [c[1] for c in calls] == ["generation-status"]


def test_broadcast_swallows_errors(monkeypatch):
    def boom():
        raise RuntimeError("pusher down")

    monkeypatch.setattr(pusher, "get_pusher", boom)
    pusher.broadcast_generation_status("proj-uid", "task-uid", 7, "uid", "success")  # must not raise


class _Db:
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _patch_db(monkeypatch, live, stored):
    monkeypatch.setattr(pusher, "get_sync_db", lambda: _Db())

    def refresh(_db):
        if isinstance(live, Exception):
            raise live
        return live

    monkeypatch.setattr(pusher, "refresh_credits_sync", refresh)
    monkeypatch.setattr(pusher, "get_stored_credits_sync", lambda _db: stored)


def test_remain_rounds_and_falls_back(monkeypatch):
    _patch_db(monkeypatch, {"total_credits": 10, "total_usage": 3.4812}, None)
    assert pusher._remain() == 6.52
    _patch_db(monkeypatch, RuntimeError("down"), {"total_credits": 50, "total_usage": 20})
    assert pusher._remain() == 30
    _patch_db(monkeypatch, None, None)
    assert pusher._remain() == 0
