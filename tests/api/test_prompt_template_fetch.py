import pytest
from datetime import timedelta
from uuid import uuid4
from services.mysql.factory.df_engine_prompt_templates import DfEnginePromptTemplatesFactory
from utils import local_time
from tests.helpers import expected_user, find_by_name, response_names

URL = "/api/prompt-management"


@pytest.mark.asyncio
async def test_fetch_all_prompt_templates(authed_client):
    """200 OK; returns the list of templates when no name filter is given."""
    resp = await authed_client.call("GET", URL)
    body = resp.json()
    assert resp.status_code == 200
    assert body["message"] == "Success"
    assert isinstance(body["data"], list)


@pytest.mark.asyncio
async def test_fetch_prompt_templates_includes_inactive_row(authed_client, user_id):
    """200 OK; inactive templates are included in the unfiltered list, same as feature-management's list."""
    inactive = DfEnginePromptTemplatesFactory.create(prompt="a prompt", is_active=False, created_by=int(user_id))
    resp = await authed_client.call("GET", URL)
    body = resp.json()
    assert resp.status_code == 200
    assert inactive.name in response_names(body)
    item = find_by_name(body["data"], inactive.name)
    assert item["is_active"] is False


@pytest.mark.asyncio
async def test_newest_first_ordering(authed_client, user_id):
    """200 OK; list is ordered by created_at descending, newest template first."""
    # `created_at` is DATETIME(0) in MySQL (no fractional seconds), so two
    # rows created back-to-back can land on the same wall-clock second —
    # pass explicit, clearly-ordered timestamps instead of relying on that.
    now = local_time()
    older = DfEnginePromptTemplatesFactory.create(
        name=f"Order {uuid4().hex[:8]}-older",
        prompt="a prompt",
        created_by=int(user_id),
        created_at=now - timedelta(seconds=5),
    )
    newer = DfEnginePromptTemplatesFactory.create(
        name=f"Order {uuid4().hex[:8]}-newer",
        prompt="a prompt",
        created_by=int(user_id),
        created_at=now,
    )

    resp = await authed_client.call("GET", URL)
    found = response_names(resp.json())
    assert found.index(newer.name) < found.index(older.name)


@pytest.mark.asyncio
async def test_name_search_is_a_prefix_match(authed_client, user_id):
    """200 OK; `name` filter matches only templates whose name starts with it, not mid-string occurrences."""
    prefix = f"Search{uuid4().hex[:8]}"
    matching = DfEnginePromptTemplatesFactory.create(name=f"{prefix}-one", prompt="a prompt", created_by=int(user_id))
    # prefix appears mid-string, shouldn't match
    DfEnginePromptTemplatesFactory.create(name=f"other-{prefix}", prompt="a prompt", created_by=int(user_id))

    resp = await authed_client.call("GET", URL, params={"name": prefix})
    found = response_names(resp.json())
    assert matching.name in found
    assert f"other-{prefix}" not in found


@pytest.mark.asyncio
async def test_name_search_includes_inactive_rows(authed_client, user_id):
    """200 OK; `name` filter still matches inactive templates, same as active ones."""
    prefix = f"Report{uuid4().hex[:8]}"
    active = DfEnginePromptTemplatesFactory.create(
        name=f"{prefix}-active", prompt="a prompt", is_active=True, created_by=int(user_id)
    )
    inactive = DfEnginePromptTemplatesFactory.create(
        name=f"{prefix}-inactive", prompt="a prompt", is_active=False, created_by=int(user_id)
    )

    resp = await authed_client.call("GET", URL, params={"name": prefix})
    found = response_names(resp.json())
    assert active.name in found
    assert inactive.name in found


@pytest.mark.asyncio
async def test_name_search_with_no_match_returns_empty_list(authed_client):
    """200 OK with an empty list when no template name matches the filter."""
    prefix = f"NoMatch{uuid4().hex[:8]}"
    resp = await authed_client.call("GET", URL, params={"name": prefix})
    assert resp.status_code == 200
    assert resp.json()["data"] == []


@pytest.mark.asyncio
async def test_name_search_empty_string_is_a_validation_error(authed_client):
    """422; empty `name` fails the query param's min_length=1 constraint."""
    resp = await authed_client.call("GET", URL, params={"name": ""}, raise_for_status=False)
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_response_shape_has_creater_not_created_by_user(authed_client, db_session, user_id):
    """200 OK; internal columns (id, created_by_user, etc.) are stripped, resolved creator/updater are exposed instead."""
    row = DfEnginePromptTemplatesFactory.create(prompt="a prompt", created_by=int(user_id))
    creator = await expected_user(db_session, user_id)

    resp = await authed_client.call("GET", URL)
    item = find_by_name(resp.json()["data"], row.name)

    assert "id" not in item
    assert "created_by" not in item
    assert "updated_by" not in item
    assert "created_by_user" not in item
    assert "updated_by_user" not in item
    assert item["creator"] == creator
    assert set(item["creator"].keys()) == {"image", "nickname"}
    assert item["updater"] is None


@pytest.mark.asyncio
async def test_no_sensitive_user_fields_leak(authed_client, user_id):
    """200 OK; `creator` is whitelisted to exactly {image, nickname}, no other user fields leak."""
    row = DfEnginePromptTemplatesFactory.create(prompt="a prompt", created_by=int(user_id))
    resp = await authed_client.call("GET", URL)
    item = find_by_name(resp.json()["data"], row.name)
    # creator is whitelisted to exactly {image, nickname} — no password,
    # no remember_token, no anything else off the real Users row.
    assert set(item["creator"].keys()) == {"image", "nickname"}


@pytest.mark.asyncio
async def test_action_flags_reflect_current_users_real_permissions(authed_client, user_id):
    """200 OK; each item's action block has exactly the fetch/update/delete flags, all booleans."""
    row = DfEnginePromptTemplatesFactory.create(prompt="a prompt", created_by=int(user_id))
    resp = await authed_client.call("GET", URL)
    item = find_by_name(resp.json()["data"], row.name)
    assert set(item["action"].keys()) == {
        "can_fetch_df_engine_prompt_templates",
        "can_delete_df_engine_prompt_template",
        "can_update_df_engine_prompt_template",
    }
    assert all(isinstance(v, bool) for v in item["action"].values())


@pytest.mark.asyncio
async def test_requires_auth(client):
    """401 when the request carries no bearer token."""
    resp = await client.call("GET", URL, raise_for_status=False)
    assert resp.status_code == 401
