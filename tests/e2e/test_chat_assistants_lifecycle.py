"""End-to-end journey of one chat: it is continued (the user message is saved and announced with `chat-insertion`),
read back without `generation_prompt`, archived (no more messages) and unarchived, then carried into a new session."""

import pytest
from tests.helpers import make_chat_session

URL = "/api/chat-assistants"
PROMPT = "Here you go\n```\nSCENE: neon city\n```"


@pytest.mark.asyncio
async def test_chat_assistant_journey(authed_client, chat_ctx, chat_settings, user_id, chat_calls):
    await chat_settings()
    session, _ = make_chat_session(
        chat_ctx, user_id, [("user", "make a prompt"), ("assistant", PROMPT, {"has_generation_prompt": True})]
    )

    # 1. continue: saved, announced once with only the user chat uid, then published to the worker
    resp = await authed_client.call("POST", f"{URL}/{session.uid}", json={"content": "shorter please"})
    user_chat_uid = resp.json()["data"]
    assert chat_calls.insertions == [("success", str(session.uid), user_chat_uid)]
    assert chat_calls.events == ["insertion", "publish"]

    # 2. read back: three messages, the new one last, no generation_prompt anywhere
    messages = (await authed_client.call("GET", f"{URL}/{session.uid}")).json()["data"]
    assert [m["uid"] for m in messages][-1] == user_chat_uid and len(messages) == 3
    assert all("generation_prompt" not in m for m in messages)

    # 3. archive: further messages are refused and nothing is announced
    chat_calls.events.clear()
    await authed_client.call("PATCH", f"{URL}/{session.uid}/set-archieve")
    refused = await authed_client.call(
        "POST", f"{URL}/{session.uid}", json={"content": "again"}, raise_for_status=False
    )
    assert refused.status_code == 422 and chat_calls.events == []

    # 4. unarchive, then transfer: allowed for a short chat, published without a chat-insertion push
    await authed_client.call("PATCH", f"{URL}/{session.uid}/set-archieve")
    chat_calls.insertions.clear()
    transfer = await authed_client.call("POST", f"{URL}/{session.uid}/transfer-knowledge")
    assert chat_calls.insertions == [] and chat_calls.events == ["publish"]
    new_uid = transfer.json()["data"]
    assert new_uid != str(session.uid) and chat_calls.published[-1]["from_session_uid"] == str(session.uid)
    assert (await authed_client.call("GET", f"{URL}/{new_uid}")).status_code == 200


@pytest.mark.asyncio
async def test_generate_prompt_journey(
    authed_client, db_session, chat_ctx, chat_settings, chat_features, user_id, chat_calls
):
    """The assistant asks, the FE reads `can_generate_prompt`, the user says yes: the worker gets the guidelines and
    the question; the button is gone right away and a second yes is refused."""
    await chat_settings()
    session, rows = make_chat_session(
        chat_ctx, user_id, [("user", "make a prompt"), ("assistant", "Write it now?", {"will_generate_prompt": True})]
    )
    asked = rows[1]

    message = (await authed_client.call("GET", f"{URL}/{session.uid}/messages/{asked.uid}")).json()["data"]
    assert message["will_generate_prompt"] is True and message["action"]["can_generate_prompt"] is True

    resp = await authed_client.call("POST", f"{URL}/{session.uid}", json={"content": "Yes", "generate_prompt": True})
    assert resp.json()["data"] != asked.uid and chat_calls.events == ["insertion", "publish"]
    assert chat_calls.published[0]["generate_prompt"] is True

    message = (await authed_client.call("GET", f"{URL}/{session.uid}/messages/{asked.uid}")).json()["data"]
    assert message["action"]["can_generate_prompt"] is False
    again = await authed_client.call(
        "POST", f"{URL}/{session.uid}", json={"content": "Yes again", "generate_prompt": True}, raise_for_status=False
    )
    assert again.status_code == 422
    gone = await authed_client.call("POST", f"{URL}/{session.uid}/generate-prompt/{asked.uid}", raise_for_status=False)
    assert gone.status_code in (404, 405)
