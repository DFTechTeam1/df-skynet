import json
import os
import pytest
import pytest_asyncio
from sqlalchemy import delete, select
from error import DataValidationError
from services.chat_assistant import CHAT_STORAGE_DIR
from services.mysql.model import DfEngineChatAssistants, DfEngineGenerations
from tests.api.test_generations_song_tasks import (  # noqa: F401  (fixtures)
    fake_generation_backends,
    pic_api_key,
    pic_employee_id,
    pic_membership,
    ranking_model,
)

URL = "/api/chat"
PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 16


@pytest_asyncio.fixture
async def assistant_model(db_session, ranking_model):
    """Chat uses only the `assistant_model` setting, so point it at the text model `ranking_model` created."""
    from services.mysql.model.df_engine_settings import DfEngineSettings
    from services.redis import CacheKeys, client as redis_client, delete_pattern

    async def _reset():
        await db_session.execute(
            delete(DfEngineSettings).where(
                DfEngineSettings.code == "admin_setting", DfEngineSettings.key == "assistant_model"
            )
        )

    previous = (
        (
            await db_session.execute(
                select(DfEngineSettings).where(
                    DfEngineSettings.code == "admin_setting", DfEngineSettings.key == "assistant_model"
                )
            )
        )
        .scalars()
        .first()
    )
    previous_value = previous.value if previous else None
    await _reset()
    db_session.add(
        DfEngineSettings(
            code="admin_setting",
            key="assistant_model",
            value=json.dumps({"uid": ranking_model.uid, "name": ranking_model.name}),
        )
    )
    await db_session.commit()
    await delete_pattern(redis_client(), CacheKeys().setting_global())
    try:
        yield ranking_model
    finally:
        await _reset()
        if previous_value is not None:  # pragma: no cover - only hit if assistant_model was already configured
            db_session.add(DfEngineSettings(code="admin_setting", key="assistant_model", value=previous_value))
        await db_session.commit()
        await delete_pattern(redis_client(), CacheKeys().setting_global())


@pytest.fixture
def fake_llm(monkeypatch):
    """Fakes the prompt validation and the OpenRouter call; records every `messages` payload sent."""
    sent = []

    class _Resp:
        status_code = 200
        is_error = False

        def raise_for_status(self):
            pass

        def json(self):
            return {
                "choices": [{"message": {"content": f"answer {len(sent)}"}}],
                "usage": {"total_tokens": 3, "cost": 0.1},
            }

    class _Caller:
        def __init__(self, *a, **k):
            pass

        async def openrouter(self, method, url, user_id, **kwargs):
            sent.append(kwargs["json"]["messages"])
            return _Resp()

        async def close(self):
            pass

    async def _ok(*a, **k):
        return None

    monkeypatch.setattr("services.chat_assistant.APICaller", _Caller)
    monkeypatch.setattr("services.chat_assistant.validate_prompt", _ok)
    return sent


def _start(client, prompt="hello", images=()):
    files = [(f"images[{i}]", (f"a{i}.png", PNG, "image/png")) for i in range(len(images))]
    return client.call("POST", f"{URL}/new", data={"prompt": prompt}, files=files or None, raise_for_status=False)


@pytest.mark.asyncio
async def test_chat_lifecycle(authed_client, pic_api_key, assistant_model, fake_llm):
    """Create with an image, list, continue (full history sent and returned), archive blocks POST, unarchive restores it."""
    resp = await _start(authed_client, images=[1])
    assert resp.status_code == 201
    chat = resp.json()["data"]
    assert [m["role"] for m in chat["messages"]] == ["user", "assistant"]
    assert chat["messages"][1]["text"] == "answer 1"
    assert chat["action"] == {"can_fetch_detail": True, "can_rename": True, "can_set_archieve": True}
    assert (chat["icon"], chat["color"]) == ("mdi-chat-outline", "green")
    image = chat["messages"][0]["images"]
    assert len(image) == 1
    stored = image[0].split("/storages/chat_assistants/")[1]
    assert os.path.exists(os.path.join(CHAT_STORAGE_DIR, stored))

    listed = (await authed_client.call("GET", "/api/chats")).json()["data"]["paginated"]
    assert chat["uid"] in [c["uid"] for c in listed]
    assert all((c["icon"], c["color"]) == ("mdi-chat-outline", "green") for c in listed)

    resp = await authed_client.call("POST", f"{URL}/{chat['uid']}", data={"prompt": "again"})
    assert resp.status_code == 200
    second = fake_llm[-1]
    assert [m["role"] for m in second] == ["system", "user", "assistant", "user"]
    assert second[2]["content"] == "answer 1"
    assert "DF Engine Assistant" in second[0]["content"]
    # the continue response already has the whole conversation: no extra GET needed
    assert [m["role"] for m in resp.json()["data"]["messages"]] == ["user", "assistant", "user", "assistant"]
    detail = (await authed_client.call("GET", f"{URL}/{chat['uid']}")).json()["data"]
    assert detail["messages"] == resp.json()["data"]["messages"]

    patched = await authed_client.call("DELETE", f"{URL}/{chat['uid']}")
    assert patched.json()["data"] is None
    blocked = await authed_client.call("POST", f"{URL}/{chat['uid']}", data={"prompt": "no"}, raise_for_status=False)
    assert blocked.status_code == 422
    archived = (await authed_client.call("GET", "/api/chats?archived=true")).json()["data"]["paginated"]
    assert chat["uid"] in [c["uid"] for c in archived]
    assert [c for c in archived if c["uid"] == chat["uid"]][0]["action"]["can_set_archieve"] is False

    await authed_client.call("DELETE", f"{URL}/{chat['uid']}")
    detail = (await authed_client.call("GET", f"{URL}/{chat['uid']}")).json()["data"]
    assert detail["action"]["can_set_archieve"] is True


@pytest.mark.asyncio
async def test_rejected_prompt_leaves_nothing_behind(
    authed_client, pic_api_key, assistant_model, fake_llm, monkeypatch, db_session
):
    """A failed guardrail aborts before any answer, chat row, generation row or stored image."""

    async def _reject(*a, **k):
        raise DataValidationError(message="prompt_nsfw_detected", context={"score": 0.9})

    before = len((await db_session.execute(select(DfEngineChatAssistants))).scalars().all())
    monkeypatch.setattr("services.chat_assistant.validate_prompt", _reject)
    resp = await _start(authed_client, prompt="bad", images=[1])
    assert resp.status_code == 422
    assert fake_llm == []
    after = len((await db_session.execute(select(DfEngineChatAssistants))).scalars().all())
    assert after == before


@pytest.mark.asyncio
async def test_invalid_image_type_is_rejected(authed_client, pic_api_key, assistant_model, fake_llm):
    resp = await authed_client.call(
        "POST",
        f"{URL}/new",
        data={"prompt": "hi"},
        files=[("images[0]", ("a.gif", b"GIF89a", "image/gif"))],
        raise_for_status=False,
    )
    assert resp.status_code == 422
    assert fake_llm == []


@pytest.mark.asyncio
async def test_rename_chat(authed_client, pic_api_key, assistant_model, fake_llm):
    chat = (await _start(authed_client)).json()["data"]
    renamed = await authed_client.call("PATCH", f"{URL}/{chat['uid']}", json={"placeholder": "  New name "})
    assert renamed.json()["data"] is None
    detail = (await authed_client.call("GET", f"{URL}/{chat['uid']}")).json()["data"]
    assert detail["placeholder"] == "New name"
    for blank in ("", "   "):
        bad = await authed_client.call(
            "PATCH", f"{URL}/{chat['uid']}", json={"placeholder": blank}, raise_for_status=False
        )
        assert bad.status_code == 422


@pytest.mark.asyncio
async def test_chat_stops_accepting_messages_at_the_limit(
    authed_client, pic_api_key, assistant_model, fake_llm, monkeypatch
):
    monkeypatch.setattr("services.chat_assistant.MAX_CHAT_MESSAGES", 2)
    chat = (await _start(authed_client)).json()["data"]
    assert (await authed_client.call("POST", f"{URL}/{chat['uid']}", data={"prompt": "two"})).status_code == 200
    blocked = await authed_client.call("POST", f"{URL}/{chat['uid']}", data={"prompt": "three"}, raise_for_status=False)
    assert blocked.status_code == 422
    detail = (await authed_client.call("GET", f"{URL}/{chat['uid']}")).json()["data"]
    assert len(detail["messages"]) == 4


@pytest.mark.asyncio
async def test_chat_list_is_paginated(authed_client, pic_api_key, assistant_model, fake_llm):
    uids = [(await _start(authed_client, prompt=f"chat {i}")).json()["data"]["uid"] for i in range(3)]
    first = (await authed_client.call("GET", "/api/chats?page=1&itemsPerPage=2")).json()["data"]
    assert len(first["paginated"]) == 2 and first["totalData"] >= 3
    assert first["paginated"][0]["uid"] == uids[-1]  # newest activity first
    second = (await authed_client.call("GET", "/api/chats?page=2&itemsPerPage=2")).json()["data"]
    assert second["paginated"] and second["paginated"][0]["uid"] not in [c["uid"] for c in first["paginated"]]


@pytest.mark.asyncio
async def test_unknown_chat_is_404(authed_client):
    resp = await authed_client.call("GET", f"{URL}/00000000-0000-0000-0000-000000000000", raise_for_status=False)
    assert resp.status_code == 404


def test_chat_action_follows_archived_at():
    from datetime import datetime
    from schemas.format.action import ChatAssistantAction

    assert ChatAssistantAction.action(None).can_set_archieve is True
    assert ChatAssistantAction.action(datetime.now()).can_set_archieve is False
    assert ChatAssistantAction.action(None).can_fetch_detail is True
