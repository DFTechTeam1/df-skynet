import services.pusher as pusher


def test_broadcast_generation_status_sends_expected_channel_event_payload(monkeypatch):
    calls = []
    monkeypatch.setattr(pusher, "get_pusher", lambda: type("Stub", (), {"trigger": lambda self, *a: calls.append(a)})())
    monkeypatch.setattr(pusher, "_remain", lambda: 6.52)

    pusher.broadcast_generation_status("proj-uid", "task-uid", "user-uid", "abc-uid", "failed", error="boom")

    ((channel, event, data),) = calls
    assert channel == "private-user-generation-project-proj-uid-task-task-uid-user-user-uid"
    assert event == "generation-status"
    assert data == {"s": "failed", "e": "boom", "gid": "abc-uid", "remain": 6.52}


def test_broadcast_generation_status_swallows_errors(monkeypatch):
    monkeypatch.setattr(pusher, "_remain", lambda: 0)

    def boom():
        raise RuntimeError("pusher down")

    monkeypatch.setattr(pusher, "get_pusher", boom)
    pusher.broadcast_generation_status("proj-uid", "task-uid", "user-uid", "uid", "processing")  # must not raise


class _Db:
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _patch_db(monkeypatch, live, stored):
    monkeypatch.setattr(pusher, "get_sync_db", lambda: _Db())
    if isinstance(live, Exception):

        def refresh(_db):
            raise live
    else:

        def refresh(_db):
            return live

    monkeypatch.setattr(pusher, "refresh_credits_sync", refresh)
    monkeypatch.setattr(pusher, "get_stored_credits_sync", lambda _db: stored)


def test_remain_int_when_whole(monkeypatch):
    _patch_db(monkeypatch, {"total_credits": 100, "total_usage": 38}, None)
    result = pusher._remain()
    assert result == 62 and isinstance(result, int)


def test_remain_float_max_two_digits(monkeypatch):
    _patch_db(monkeypatch, {"total_credits": 10, "total_usage": 3.4812}, None)
    assert pusher._remain() == 6.52


def test_remain_falls_back_to_stored_then_zero(monkeypatch):
    _patch_db(monkeypatch, RuntimeError("down"), {"total_credits": 50, "total_usage": 20})
    assert pusher._remain() == 30
    _patch_db(monkeypatch, None, None)
    assert pusher._remain() == 0
