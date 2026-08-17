import pytest
from datetime import timedelta
from uuid import uuid4
from services.mysql.model import DfEnginePromptTemplates
from utils import local_time
from tests.helpers import create_record, expected_user, find_by_name, response_names

URL = "/api/prompt-management"


@pytest.mark.asyncio
async def test_fetch_all_prompt_templates(authed_client):
    resp = await authed_client.call("GET", URL)
    body = resp.json()
    assert resp.status_code == 200
    assert body["message"] == "Success"
    assert all(item["is_active"] is True for item in body["data"])


@pytest.mark.asyncio
async def test_fetch_prompt_templates_inactive_row_is_excluded(
    authed_client, db_session, user_id
):
    inactive = await create_record(
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
    resp = await authed_client.call("GET", URL)
    body = resp.json()
    assert resp.status_code == 200
    assert all(item["is_active"] is True for item in body["data"])
    assert inactive.name not in response_names(body)


@pytest.mark.asyncio
async def test_newest_first_ordering(authed_client, db_session, user_id):
    # `created_at` is DATETIME(0) in MySQL (no fractional seconds), so two
    # rows created back-to-back can land on the same wall-clock second —
    # pass explicit, clearly-ordered timestamps instead of relying on that.
    now = local_time()
    older = await create_record(
        db_session,
        DfEnginePromptTemplates,
        dict(
            uid=str(uuid4()),
            name=f"Order {uuid4().hex[:8]}-older",
            prompt="a prompt",
            created_by=int(user_id),
            created_at=now - timedelta(seconds=5),
        ),
    )
    newer = await create_record(
        db_session,
        DfEnginePromptTemplates,
        dict(
            uid=str(uuid4()),
            name=f"Order {uuid4().hex[:8]}-newer",
            prompt="a prompt",
            created_by=int(user_id),
            created_at=now,
        ),
    )

    resp = await authed_client.call("GET", URL)
    found = response_names(resp.json())
    assert found.index(newer.name) < found.index(older.name)


@pytest.mark.asyncio
async def test_name_search_is_a_prefix_match(authed_client, db_session, user_id):
    prefix = f"Search{uuid4().hex[:8]}"
    matching = await create_record(
        db_session,
        DfEnginePromptTemplates,
        dict(
            uid=str(uuid4()),
            name=f"{prefix}-one",
            prompt="a prompt",
            created_by=int(user_id),
        ),
    )
    # prefix appears mid-string, shouldn't match
    await create_record(
        db_session,
        DfEnginePromptTemplates,
        dict(
            uid=str(uuid4()),
            name=f"other-{prefix}",
            prompt="a prompt",
            created_by=int(user_id),
        ),
    )

    resp = await authed_client.call("GET", URL, params={"name": prefix})
    found = response_names(resp.json())
    assert matching.name in found
    assert f"other-{prefix}" not in found


@pytest.mark.asyncio
async def test_name_search_excludes_inactive_rows(authed_client, db_session, user_id):
    prefix = f"Report{uuid4().hex[:8]}"
    active = await create_record(
        db_session,
        DfEnginePromptTemplates,
        dict(
            uid=str(uuid4()),
            name=f"{prefix}-active",
            prompt="a prompt",
            is_active=True,
            created_by=int(user_id),
        ),
    )
    inactive = await create_record(
        db_session,
        DfEnginePromptTemplates,
        dict(
            uid=str(uuid4()),
            name=f"{prefix}-inactive",
            prompt="a prompt",
            is_active=False,
            created_by=int(user_id),
        ),
    )

    resp = await authed_client.call("GET", URL, params={"name": prefix})
    found = response_names(resp.json())
    assert active.name in found
    assert inactive.name not in found


@pytest.mark.asyncio
async def test_name_search_with_no_match_returns_empty_list(authed_client):
    prefix = f"NoMatch{uuid4().hex[:8]}"
    resp = await authed_client.call("GET", URL, params={"name": prefix})
    assert resp.status_code == 200
    assert resp.json()["data"] == []


@pytest.mark.asyncio
async def test_name_search_empty_string_is_a_validation_error(authed_client):
    resp = await authed_client.call(
        "GET", URL, params={"name": ""}, raise_for_status=False
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_response_shape_has_creater_not_created_by_user(
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
    creater = await expected_user(db_session, user_id)

    resp = await authed_client.call("GET", URL)
    item = find_by_name(resp.json()["data"], row.name)

    assert "id" not in item
    assert "created_by" not in item
    assert "updated_by" not in item
    assert "created_by_user" not in item
    assert "updated_by_user" not in item
    assert item["creater"] == creater
    assert set(item["creater"].keys()) == {"image", "nickname"}
    assert item["updater"] is None


@pytest.mark.asyncio
async def test_no_sensitive_user_fields_leak(authed_client, db_session, user_id):
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
    resp = await authed_client.call("GET", URL)
    item = find_by_name(resp.json()["data"], row.name)
    # creater is whitelisted to exactly {image, nickname} — no password,
    # no remember_token, no anything else off the real Users row.
    assert set(item["creater"].keys()) == {"image", "nickname"}


@pytest.mark.asyncio
async def test_action_flags_reflect_current_users_real_permissions(
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
    resp = await authed_client.call("GET", URL)
    item = find_by_name(resp.json()["data"], row.name)
    assert set(item["action"].keys()) == {
        "can_fetch_prompt_templates",
        "can_delete_prompt_template",
        "can_update_prompt_template",
        "can_create_prompt_template",
    }
    assert all(isinstance(v, bool) for v in item["action"].values())


@pytest.mark.asyncio
async def test_requires_auth(client):
    resp = await client.call("GET", URL, raise_for_status=False)
    assert resp.status_code == 401
