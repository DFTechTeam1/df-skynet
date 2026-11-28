from datetime import datetime
from schemas.format.chat_assistants import ChatMessage

USER = {"id": 68, "image": "me.png", "employees": {"nickname": "zed McKay"}}


def _row(**extra):
    return {
        "uid": "u1",
        "content": "here\n```\nSCENE: x\n```",
        "created_by_user": None,
        "status_code": 200,
        "has_generation_prompt": True,
        "chat_references": [],
        **extra,
    }


def test_message_has_no_generation_prompt_key():
    dumped = ChatMessage.format(_row()).model_dump()
    assert "generation_prompt" not in dumped
    assert dumped["has_generation_prompt"] is True and "```" in dumped["content"]


def test_waiting_reply_can_generate_prompt():
    dumped = ChatMessage.format(_row(has_generation_prompt=False, will_generate_prompt=True)).model_dump()
    assert dumped["will_generate_prompt"] is True and dumped["action"]["can_generate_prompt"] is True


def test_only_a_successful_openrouter_reply_can_generate_prompt():
    for row in (
        _row(will_generate_prompt=False),
        _row(will_generate_prompt=True, created_by_user=USER),
        _row(will_generate_prompt=True, status_code=502),
        _row(),  # key missing (old rows, partial loads)
    ):
        assert ChatMessage.format(row).action.can_generate_prompt is False


def test_only_a_failed_user_message_can_be_resent():
    assert ChatMessage.format(_row(status_code=400, created_by_user=USER)).action.can_resend is True
    assert ChatMessage.format(_row(status_code=200, created_by_user=USER)).action.can_resend is False
    assert ChatMessage.format(_row(status_code=400)).action.can_resend is False


def test_sent_at_icon_and_color_follow_the_status_code():
    ok = ChatMessage.format(_row(sent_at=datetime(2026, 11, 27, 10, 0))).model_dump()
    assert ok["sent_at"] and (ok["icon"], ok["color"]) == ("mdi-check-circle", "green")
    failed = ChatMessage.format(_row(status_code=502)).model_dump()
    assert (failed["icon"], failed["color"]) == ("mdi-alert-circle", "red")


def test_creator_is_the_user_or_openrouter():
    mine = ChatMessage.format(_row(created_by_user=USER)).model_dump()
    assert mine["sender"] == "Zed Mckay" and mine["creator"] == {
        "user_id": 68,
        "image": "me.png",
        "nickname": "Zed Mckay",
    }
    nameless = _row(role="user", created_by_user={**USER, "employees": None})
    assert ChatMessage.format(nameless).sender == "User"
    reply = ChatMessage.format(_row(role="assistant"))
    assert reply.sender == "Openrouter"
    bot = reply.model_dump()["creator"]
    assert (
        bot["user_id"] is None and bot["nickname"] == "Openrouter" and bot["image"].startswith("https://openrouter.ai/")
    )
