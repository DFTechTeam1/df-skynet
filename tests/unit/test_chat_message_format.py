from schemas.format.chat_assistants import ChatMessage


def test_message_has_no_generation_prompt_key():
    row = {
        "uid": "u1",
        "content": "here\n```\nSCENE: x\n```",
        "sender": "openrouter",
        "status_code": 200,
        "has_generation_prompt": True,
        "chat_references": [],
    }
    dumped = ChatMessage.format(row).model_dump()
    assert "generation_prompt" not in dumped
    assert dumped["has_generation_prompt"] is True and "```" in dumped["content"]
