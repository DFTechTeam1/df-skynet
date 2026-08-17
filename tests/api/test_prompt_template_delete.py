import pytest
from uuid import uuid4
from middlewares.lang import resolve_message
from services.mysql.model import (
    DfEngineActionMappings,
    DfEngineActions,
    DfEnginePromptTemplates,
)
from tests.helpers import create_record, response_names

URL = "/api/prompt-management"


@pytest.mark.asyncio
async def test_delete_success(authed_client, db_session, user_id):
    row = await create_record(
        db_session,
        DfEnginePromptTemplates,
        dict(
            uid=str(uuid4()),
            name=f"Prompt {uuid4().hex[:8]}",
            prompt="a prompt",
            created_by=int(user_id),
        ),
    )
    resp = await authed_client.call("DELETE", f"{URL}/{row.uid}")
    assert resp.status_code == 200
    assert row.name not in response_names(resp.json())


@pytest.mark.asyncio
async def test_delete_twice_is_404_on_the_second_call(
    authed_client, db_session, user_id
):
    row = await create_record(
        db_session,
        DfEnginePromptTemplates,
        dict(
            uid=str(uuid4()),
            name=f"Prompt {uuid4().hex[:8]}",
            prompt="a prompt",
            created_by=int(user_id),
        ),
    )
    first = await authed_client.call("DELETE", f"{URL}/{row.uid}")
    assert first.status_code == 200
    second = await authed_client.call(
        "DELETE", f"{URL}/{row.uid}", raise_for_status=False
    )
    assert second.status_code == 404
    assert second.json()["message"] == resolve_message(
        "prompt_template_not_found", "en"
    )


@pytest.mark.asyncio
async def test_delete_unknown_uid_is_404(authed_client):
    resp = await authed_client.call(
        "DELETE", f"{URL}/{uuid4()}", raise_for_status=False
    )
    assert resp.status_code == 404
    assert resp.json()["message"] == resolve_message("prompt_template_not_found", "en")


@pytest.mark.asyncio
async def test_delete_blocked_while_mapped_to_an_action(
    authed_client, db_session, user_id
):
    row = await create_record(
        db_session,
        DfEnginePromptTemplates,
        dict(
            uid=str(uuid4()),
            name=f"Prompt {uuid4().hex[:8]}",
            prompt="a prompt",
            created_by=int(user_id),
        ),
    )
    action = await create_record(
        db_session,
        DfEngineActions,
        dict(
            uid=str(uuid4()),
            name=f"Action {uuid4().hex[:8]}",
            created_by=int(user_id),
        ),
    )
    await create_record(
        db_session,
        DfEngineActionMappings,
        dict(uid=str(uuid4()), action_id=action.id, template_id=row.id),
    )

    resp = await authed_client.call(
        "DELETE", f"{URL}/{row.uid}", raise_for_status=False
    )
    assert resp.status_code == 409
    assert resp.json()["message"] == resolve_message("prompt_template_in_use", "en")
    assert "data" not in resp.json()

    still_present = await authed_client.call("GET", URL)
    assert row.name in response_names(still_present.json())


@pytest.mark.asyncio
async def test_requires_auth(client, db_session, user_id):
    row = await create_record(
        db_session,
        DfEnginePromptTemplates,
        dict(
            uid=str(uuid4()),
            name=f"Prompt {uuid4().hex[:8]}",
            prompt="a prompt",
            created_by=int(user_id),
        ),
    )
    resp = await client.call("DELETE", f"{URL}/{row.uid}", raise_for_status=False)
    assert resp.status_code == 401


# --- localization ------------------------------------------------------------


@pytest.mark.asyncio
async def test_not_found_message_respects_accept_language(authed_client):
    unknown_uid = uuid4()

    en_resp = await authed_client.call(
        "DELETE",
        f"{URL}/{unknown_uid}",
        headers={"Accept-Language": "en"},
        raise_for_status=False,
    )
    id_resp = await authed_client.call(
        "DELETE",
        f"{URL}/{unknown_uid}",
        headers={"Accept-Language": "id"},
        raise_for_status=False,
    )

    assert en_resp.json()["message"] == resolve_message(
        "prompt_template_not_found", "en"
    )
    assert id_resp.json()["message"] == resolve_message(
        "prompt_template_not_found", "id"
    )
    assert en_resp.json()["message"] != id_resp.json()["message"]
