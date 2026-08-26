import pytest
from datetime import timedelta
from uuid import uuid4
from services.mysql.factory.df_engine_feature_prompt_mappings import DfEngineFeaturePromptMappingsFactory
from services.mysql.factory.df_engine_features import DfEngineFeaturesFactory
from services.mysql.factory.df_engine_prompt_templates import DfEnginePromptTemplatesFactory
from utils import local_time
from tests.helpers import expected_user, find_by_name, response_names

URL = "/api/feature-management"


@pytest.mark.asyncio
async def test_fetch_all_features(authed_client):
    """200 OK; returns a list when no name filter is given."""
    resp = await authed_client.call("GET", URL)
    body = resp.json()
    assert resp.status_code == 200
    assert body["message"] == "Success"
    assert isinstance(body["data"], list)


@pytest.mark.asyncio
async def test_fetch_includes_inactive_features(authed_client, user_id):
    """200 OK; list includes inactive features too, unlike the prompt-template list."""
    inactive = DfEngineFeaturesFactory.create(
        is_active=False, created_by=int(user_id), df_engine_feature_prompt_mapping=None
    )
    resp = await authed_client.call("GET", URL)
    body = resp.json()
    assert resp.status_code == 200
    item = find_by_name(body["data"], inactive.name)
    assert item["is_active"] is False


@pytest.mark.asyncio
async def test_newest_first_ordering(authed_client, user_id):
    """200 OK; list is ordered by created_at descending, newest feature first."""
    # `created_at` is DATETIME(0) in MySQL (no fractional seconds), so two
    # rows created back-to-back can land on the same wall-clock second —
    # pass explicit, clearly-ordered timestamps instead of relying on that.
    now = local_time()
    older = DfEngineFeaturesFactory.create(
        name=f"Order {uuid4().hex[:8]}-older",
        created_by=int(user_id),
        created_at=now - timedelta(seconds=5),
        df_engine_feature_prompt_mapping=None,
    )
    newer = DfEngineFeaturesFactory.create(
        name=f"Order {uuid4().hex[:8]}-newer",
        created_by=int(user_id),
        created_at=now,
        df_engine_feature_prompt_mapping=None,
    )

    resp = await authed_client.call("GET", URL)
    found = response_names(resp.json())
    assert found.index(newer.name) < found.index(older.name)


@pytest.mark.asyncio
async def test_name_search_is_a_prefix_match(authed_client, user_id):
    """200 OK; `name` filter matches only features whose name starts with it, not mid-string occurrences."""
    prefix = f"Search{uuid4().hex[:8]}"
    matching = DfEngineFeaturesFactory.create(
        name=f"{prefix}-one", created_by=int(user_id), df_engine_feature_prompt_mapping=None
    )
    # prefix appears mid-string, shouldn't match
    DfEngineFeaturesFactory.create(
        name=f"other-{prefix}", created_by=int(user_id), df_engine_feature_prompt_mapping=None
    )

    resp = await authed_client.call("GET", URL, params={"name": prefix})
    found = response_names(resp.json())
    assert matching.name in found
    assert f"other-{prefix}" not in found


@pytest.mark.asyncio
async def test_name_search_with_no_match_returns_empty_list(authed_client):
    """200 OK with an empty list when no feature name matches the filter."""
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
    row = DfEngineFeaturesFactory.create(created_by=int(user_id), df_engine_feature_prompt_mapping=None)
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
async def test_action_flags_reflect_current_users_real_permissions(authed_client, user_id):
    """200 OK; each item's action block has exactly the fetch-detail/update/delete flags, all booleans."""
    row = DfEngineFeaturesFactory.create(created_by=int(user_id), df_engine_feature_prompt_mapping=None)
    resp = await authed_client.call("GET", URL)
    item = find_by_name(resp.json()["data"], row.name)
    assert set(item["action"].keys()) == {
        "can_fetch_detail",
        "can_update_feature",
        "can_delete_feature",
    }
    assert all(isinstance(v, bool) for v in item["action"].values())


@pytest.mark.asyncio
async def test_templates_array_is_empty_when_unlinked(authed_client, user_id):
    """200 OK; `templates` is an empty list for a feature with no df_engine_feature_prompt_mappings rows."""
    row = DfEngineFeaturesFactory.create(created_by=int(user_id), df_engine_feature_prompt_mapping=None)
    resp = await authed_client.call("GET", URL)
    item = find_by_name(resp.json()["data"], row.name)
    assert item["templates"] == []


@pytest.mark.asyncio
async def test_templates_array_reflects_linked_rows(authed_client, user_id):
    """200 OK; `templates` nests the mapped prompt template's own fields via the join table."""
    feature = DfEngineFeaturesFactory.create(created_by=int(user_id), df_engine_feature_prompt_mapping=None)
    template = DfEnginePromptTemplatesFactory.create(prompt="a prompt", created_by=int(user_id))
    mapping = DfEngineFeaturePromptMappingsFactory.create(
        df_engine_features=feature, df_engine_prompt_templates=template
    )

    resp = await authed_client.call("GET", URL)
    item = find_by_name(resp.json()["data"], feature.name)
    assert len(item["templates"]) == 1
    entry = item["templates"][0]
    assert entry["template_uid"] == template.uid
    assert entry["name"] == template.name
    assert entry["is_active"] is True


@pytest.mark.asyncio
async def test_templates_array_excludes_inactive_mapped_templates(authed_client, user_id):
    """200 OK; `templates` omits a mapped template whose is_active is False, even though the mapping row still exists."""
    feature = DfEngineFeaturesFactory.create(created_by=int(user_id), df_engine_feature_prompt_mapping=None)
    inactive_template = DfEnginePromptTemplatesFactory.create(
        prompt="a prompt", is_active=False, created_by=int(user_id)
    )
    DfEngineFeaturePromptMappingsFactory.create(
        df_engine_features=feature, df_engine_prompt_templates=inactive_template
    )

    resp = await authed_client.call("GET", URL)
    item = find_by_name(resp.json()["data"], feature.name)
    assert item["templates"] == []


@pytest.mark.asyncio
async def test_requires_auth(client):
    """401 when the request carries no bearer token."""
    resp = await client.call("GET", URL, raise_for_status=False)
    assert resp.status_code == 401
