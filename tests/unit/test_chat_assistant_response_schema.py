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


A, B = "e21af800-eb5f-4ab9-af3d-0029ef6b75e9", "2f835496-c47c-496d-b8b4-b4512ff6248a"


def _payload(content, **kw):
    from schemas.payload.chat_assistants import ContinueSessionPayload

    files = [{"file_uid": A, "type": "generated"}, {"file_uid": B, "type": "generated"}]
    return ContinueSessionPayload(content=content, attachments=files, **kw)


def test_attached_files_named_in_the_text_become_refer_tags():
    out = _payload(f"ini gambar apa ya?? {A}, sama ini juga apa ya??{B}")
    assert out.content == f"ini gambar apa ya?? <refer to {A}>, sama ini juga apa ya??<refer to {B}>"


def test_tags_already_written_are_not_wrapped_again_and_case_is_ignored():
    out = _payload(f"<refer to {A}> and {B.upper()}")
    assert out.content == f"<refer to {A}> and <refer to {B}>"


def test_a_file_named_twice_is_tagged_everywhere_and_other_ids_are_untouched():
    other = "11111111-1111-1111-1111-111111111111"
    out = _payload(f"{A} {B} {A} {other}")
    assert out.content == f"<refer to {A}> <refer to {B}> <refer to {A}> {other}"


def test_a_message_without_attachments_is_not_changed():
    from schemas.payload.chat_assistants import ContinueSessionPayload

    assert ContinueSessionPayload(content=f"{A} stays").content == f"{A} stays"


def test_an_attached_file_the_text_never_names_is_refused():
    import pytest
    from error import DataValidationError

    with pytest.raises(DataValidationError):
        _payload(f"only {A} here")
