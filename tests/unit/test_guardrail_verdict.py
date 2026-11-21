from services.rmq.consumer import classify


def test_priority_order():
    assert classify({"prompt_injection": True, "nfsw": True, "chat_assistant": True}) == (
        "guardrail_prompt_injection",
        None,
        True,
    )
    assert classify({"nfsw": True, "chat_assistant": True}) == ("guardrail_nsfw", None, True)
    assert classify({"image_generation": True}) == ("guardrail_use_case", "image_generation", False)
    assert classify({"chat_assistant": True, "image_generation": True})[1] == "chat_assistant"
    assert classify({}) == ("guardrail_no_use_case", None, False)
