import services.pusher as pusher


def test_broadcast_generation_status_sends_expected_channel_event_payload(monkeypatch):
    calls = []
    monkeypatch.setattr(pusher, "get_pusher", lambda: type("Stub", (), {"trigger": lambda self, *a: calls.append(a)})())

    pusher.broadcast_generation_status("proj-uid", "task-uid", "user-uid", "abc-uid", "failed", error="boom")

    ((channel, event, data),) = calls
    assert channel == "private-user-generation-project-proj-uid-task-task-uid-user-user-uid"
    assert event == "generation-status"
    assert data == {"s": "failed", "e": "boom", "gid": "abc-uid"}


def test_broadcast_generation_status_swallows_errors(monkeypatch):
    def boom():
        raise RuntimeError("pusher down")

    monkeypatch.setattr(pusher, "get_pusher", boom)
    pusher.broadcast_generation_status("proj-uid", "task-uid", "user-uid", "uid", "processing")  # must not raise
