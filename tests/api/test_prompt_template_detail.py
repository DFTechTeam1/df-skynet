import pytest
from uuid import uuid4
from middlewares.lang import resolve_message
from services.mysql.model import DfEnginePromptTemplates
from tests.helpers import create_record, expected_user

URL = "/api/prompt-management"


@pytest.mark.asyncio
async def test_fetch_detail_success(authed_client, db_session, user_id):
    """200 OK; returns the single template's own name/prompt/is_active by uid."""
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
    resp = await authed_client.call("GET", f"{URL}/{row.uid}")
    body = resp.json()
    assert resp.status_code == 200
    assert body["message"] == "Success"
    assert body["data"]["name"] == row.name
    assert body["data"]["prompt"] == row.prompt
    assert body["data"]["is_active"] is True


@pytest.mark.asyncio
async def test_fetch_detail_response_shape_has_creater_not_created_by_user(authed_client, db_session, user_id):
    """200 OK; internal columns (id, created_by_user, etc.) are stripped, resolved creater/updater are exposed instead."""
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
    creater = await expected_user(db_session, user_id)

    resp = await authed_client.call("GET", f"{URL}/{row.uid}")
    item = resp.json()["data"]

    assert "id" not in item
    assert "created_by" not in item
    assert "updated_by" not in item
    assert "created_by_user" not in item
    assert "updated_by_user" not in item
    assert item["creater"] == creater
    assert set(item["creater"].keys()) == {"image", "nickname"}
    assert item["updater"] is None


@pytest.mark.asyncio
async def test_fetch_detail_action_flags_reflect_current_users_real_permissions(authed_client, db_session, user_id):
    """200 OK; action block has exactly the fetch/update/delete flags, all booleans."""
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
    resp = await authed_client.call("GET", f"{URL}/{row.uid}")
    item = resp.json()["data"]
    assert set(item["action"].keys()) == {
        "can_fetch_df_engine_prompt_templates",
        "can_delete_df_engine_prompt_template",
        "can_update_df_engine_prompt_template",
    }
    assert all(isinstance(v, bool) for v in item["action"].values())


@pytest.mark.asyncio
async def test_fetch_detail_unknown_uid_is_404(authed_client):
    """404 prompt_template_not_found when the uid matches no template."""
    resp = await authed_client.call("GET", f"{URL}/{uuid4()}", raise_for_status=False)
    assert resp.status_code == 404
    assert resp.json()["message"] == resolve_message("prompt_template_not_found", "en")


@pytest.mark.asyncio
async def test_fetch_detail_inactive_row_is_404(authed_client, db_session, user_id):
    """404 prompt_template_not_found; detail only serves active templates, same as the list endpoint."""
    row = await create_record(
        db_session,
        DfEnginePromptTemplates,
        dict(
            uid=str(uuid4()),
            name=f"Prompt {uuid4().hex[:8]}",
            prompt="a prompt",
            is_active=False,
            created_by=int(user_id),
        ),
    )
    resp = await authed_client.call("GET", f"{URL}/{row.uid}", raise_for_status=False)
    assert resp.status_code == 404
    assert resp.json()["message"] == resolve_message("prompt_template_not_found", "en")


@pytest.mark.asyncio
async def test_fetch_detail_requires_auth(client, db_session, user_id):
    """401 when the request carries no bearer token."""
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
    resp = await client.call("GET", f"{URL}/{row.uid}", raise_for_status=False)
    assert resp.status_code == 401


# --- localization ------------------------------------------------------------


@pytest.mark.asyncio
async def test_fetch_detail_not_found_message_respects_accept_language(authed_client):
    """404 for both, but the message text differs between Accept-Language: en and id."""
    unknown_uid = uuid4()

    en_resp = await authed_client.call(
        "GET",
        f"{URL}/{unknown_uid}",
        headers={"Accept-Language": "en"},
        raise_for_status=False,
    )
    id_resp = await authed_client.call(
        "GET",
        f"{URL}/{unknown_uid}",
        headers={"Accept-Language": "id"},
        raise_for_status=False,
    )

    assert en_resp.json()["message"] == resolve_message("prompt_template_not_found", "en")
    assert id_resp.json()["message"] == resolve_message("prompt_template_not_found", "id")
    assert en_resp.json()["message"] != id_resp.json()["message"]
