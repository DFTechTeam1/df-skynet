import pytest
from validations import prompt as prompt_module


@pytest.mark.asyncio
async def test_enhance_prompt_sends_images_as_input_parts(monkeypatch):
    sent = {}

    class FakeCaller:
        def __init__(self, *a, **k): ...

        async def openrouter(self, method, path, user_id=None, json=None):
            sent.update(json)

            class R:
                is_error = False
                status_code = 200

                def json(self):
                    return {"output": [{"type": "message", "content": [{"type": "output_text", "text": "ok"}]}]}

            return R()

        async def close(self): ...

    monkeypatch.setattr(prompt_module, "APICaller", FakeCaller)
    await prompt_module.enhance_prompt("a bird u1", "m", "k", 1, ["https://x/a.png"])
    parts = sent["input"][0]["content"]
    assert parts[0]["type"] == "input_text" and parts[1] == {"type": "input_image", "image_url": "https://x/a.png"}
    assert "REFERENCE IMAGES" in sent["instructions"]
