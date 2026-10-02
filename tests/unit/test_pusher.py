import services.pusher as pusher


def test_broadcast_generation_status_sends_expected_channel_event_payload(monkeypatch):
    calls = []
    monkeypatch.setattr(pusher, "get_pusher", lambda: type("Stub", (), {"trigger": lambda self, *a: calls.append(a)})())

    pusher.broadcast_generation_status(3, 5, 7, "abc-uid", "failed", error="boom")

    ((channel, event, data),) = calls
    assert channel == "private-user-generation-project-3-task-5-user-7"
    assert event == "generation-status"
    assert data == {"s": "failed", "e": "boom", "gid": "abc-uid"}


def test_broadcast_generation_status_swallows_errors(monkeypatch):
    def boom():
        raise RuntimeError("pusher down")

    monkeypatch.setattr(pusher, "get_pusher", boom)
    pusher.broadcast_generation_status(3, 5, 1, "uid", "processing")  # must not raise
