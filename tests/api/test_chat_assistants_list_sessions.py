import pytest
from tests.helpers import make_chat_session


def _url(ctx, suffix=""):
    return f"/api/projects/{ctx.project_uid}/chat-assistants/{ctx.menu_uid}{suffix}"


@pytest.mark.asyncio
async def test_list_returns_own_sessions_and_filters_by_topic_and_archive(
    authed_client, chat_ctx, user_id, other_user_id
):
    """200; own sessions only, topic search is case-insensitive, `archieved` splits archived from active."""
    active, _ = make_chat_session(chat_ctx, user_id, [("user", "hi")])
    archived, _ = make_chat_session(chat_ctx, user_id, [("user", "hi")], archieved=True)
    foreign, _ = make_chat_session(chat_ctx, other_user_id, [("user", "hi")])

    everything = (await authed_client.call("GET", _url(chat_ctx, "?itemsPerPage=100"))).json()["data"]["paginated"]
    uids = {s["uid"] for s in everything}
    assert {active.uid, archived.uid} <= uids and foreign.uid not in uids

    only_archived = (await authed_client.call("GET", _url(chat_ctx, "?archieved=true&itemsPerPage=100"))).json()["data"]
    assert archived.uid in {s["uid"] for s in only_archived["paginated"]}
    assert active.uid not in {s["uid"] for s in only_archived["paginated"]}

    only_active = (await authed_client.call("GET", _url(chat_ctx, "?archieved=false&itemsPerPage=100"))).json()["data"]
    assert active.uid in {s["uid"] for s in only_active["paginated"]}

    found = (await authed_client.call("GET", _url(chat_ctx, f"?topic={active.topic.upper()}"))).json()["data"]
    assert [s["uid"] for s in found["paginated"]] == [active.uid] and found["totalData"] == 1
