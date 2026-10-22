from unittest.mock import MagicMock
from services import slack_notifier as sn


def test_notify_logs_in_then_sends_with_bearer(monkeypatch):
    monkeypatch.setattr(sn, "LOGIN_URL", "http://x/api")
    monkeypatch.setattr(sn, "ERP_EMAIL", "a@b.c")
    monkeypatch.setattr(sn, "ERP_PASSWORD", "pw")
    login = MagicMock(is_error=False)
    login.json.return_value = {"data": {"access_token": "tok"}}
    sent = MagicMock(is_error=False)
    caller = MagicMock()
    caller.call_sync.side_effect = [login, sent]
    monkeypatch.setattr(sn, "APICaller", lambda **_: caller)
    sn.notify_udin_upload_failed("uid-1", "Proj", "boom")
    (_, p1, *_), _ = caller.call_sync.call_args_list[0]
    (_, p2, *_), kw = caller.call_sync.call_args_list[1]
    assert p1 == "/auth/login" and p2 == "/system-slack/send-message"
    assert kw["headers"]["Authorization"] == "Bearer tok"
    assert kw["json"]["messageTitle"] and kw["json"]["title"]


def test_notify_never_raises(monkeypatch):
    monkeypatch.setattr(sn, "LOGIN_URL", "http://x")
    monkeypatch.setattr(sn, "ERP_EMAIL", "a")
    monkeypatch.setattr(sn, "ERP_PASSWORD", "b")
    monkeypatch.setattr(sn, "APICaller", lambda **_: (_ for _ in ()).throw(RuntimeError("x")))
    sn.notify_udin_upload_failed("u", "p", "d")


def test_reupload_lock_released_on_failure(monkeypatch):
    from services.tasks import base

    redis = MagicMock()
    monkeypatch.setattr(base, "sync_client", lambda: redis)
    base._release_reupload_lock(7)
    redis.delete.assert_called_once_with("generation_reupload_lock:7")
