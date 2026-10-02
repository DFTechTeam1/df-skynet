from apps.controller.pusher import CHANNEL_RE


def test_channel_re_extracts_owning_user_id():
    match = CHANNEL_RE.match("private-user-generation-project-9-task-3-user-42")
    assert match and match.group(1) == "42"


def test_channel_re_rejects_mismatched_user_id():
    match = CHANNEL_RE.match("private-user-generation-project-9-task-3-user-99")
    assert match.group(1) != "42"


def test_channel_re_rejects_non_private_channel():
    assert CHANNEL_RE.match("user-generation-project-9-task-3-user-42") is None
