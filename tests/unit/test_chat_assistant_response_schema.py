from schemas.format.openrouter import ChatAssistantResponse


def test_will_generate_prompt_is_a_required_strict_field():
    schema = ChatAssistantResponse.model_json_schema()
    assert "will_generate_prompt" in schema["required"] and "has_generation_prompt" in schema["required"]
    assert schema["additionalProperties"] is False
    fmt = ChatAssistantResponse.response_format("chat_reply")
    assert fmt["json_schema"]["strict"] is True


def test_the_pop_up_flag_parses_next_to_the_prompt_flag():
    reply = ChatAssistantResponse.model_validate_json(
        '{"content": "Write it?", "attachments": [], "will_generate_prompt": true, "has_generation_prompt": false}',
        strict=True,
    )
    assert reply.will_generate_prompt and not reply.has_generation_prompt


def test_continue_payload_generate_prompt_defaults_to_false():
    from schemas.payload.chat_assistants import ContinueSessionPayload

    assert ContinueSessionPayload(content="hi").generate_prompt is False
    assert ContinueSessionPayload(content="yes", generate_prompt=True).generate_prompt is True
