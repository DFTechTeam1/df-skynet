from schemas.format.chat_assistants import ChatMessage


def _row(**extra):
    return {
        "uid": "u1",
        "content": "here\n```\nSCENE: x\n```",
        "sender": "openrouter",
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
        _row(will_generate_prompt=True, sender="tester"),
        _row(will_generate_prompt=True, status_code=502),
        _row(),  # key missing (old rows, partial loads)
    ):
        assert ChatMessage.format(row).action.can_generate_prompt is False


def test_only_a_failed_user_message_can_be_resent():
    assert ChatMessage.format(_row(status_code=400, sender="bastian")).action.can_resend is True
    assert ChatMessage.format(_row(status_code=200, sender="bastian")).action.can_resend is False
    assert ChatMessage.format(_row(status_code=400, sender="openrouter")).action.can_resend is False
