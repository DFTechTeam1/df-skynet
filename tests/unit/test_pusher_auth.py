from apps.controller.pusher import CHANNEL_RE

PROJECT_UID = "11111111-1111-1111-1111-111111111111"
TASK_UID = "22222222-2222-2222-2222-222222222222"
USER_UID = "33333333-3333-3333-3333-333333333333"
OTHER_USER_UID = "44444444-4444-4444-4444-444444444444"


def test_channel_re_extracts_project_task_and_user_uids():
    match = CHANNEL_RE.match(f"private-user-generation-project-{PROJECT_UID}-task-{TASK_UID}-user-{USER_UID}")
    assert match and match.groups() == (PROJECT_UID, TASK_UID, USER_UID)


def test_channel_re_rejects_mismatched_user_uid():
    match = CHANNEL_RE.match(f"private-user-generation-project-{PROJECT_UID}-task-{TASK_UID}-user-{OTHER_USER_UID}")
    assert match.group(3) != USER_UID


def test_channel_re_rejects_non_private_channel():
    assert CHANNEL_RE.match(f"user-generation-project-{PROJECT_UID}-task-{TASK_UID}-user-{USER_UID}") is None


def test_channel_re_rejects_malformed_uid_segment():
    assert CHANNEL_RE.match("private-user-generation-project-not-a-uuid-task-not-a-uuid-user-not-a-uuid") is None
