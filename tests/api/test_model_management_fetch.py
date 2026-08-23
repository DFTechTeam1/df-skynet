import pytest
from typing import Any
from uuid import uuid4
from services.mysql.model import DfEngineModelOptions
from tests.helpers import create_record

URL = "/api/models"


def _model_option_data(**overrides: Any) -> dict[str, Any]:
    unique = uuid4().hex[:10]
    data = dict(
        uid=str(uuid4()),
        model_id=f"test-vendor/test-model-{unique}",
        name=f"FetchTest-{unique}",
        type="text",
        is_available=True,
        is_enabled=False,
        is_main=False,
    )
    data.update(overrides)
    return data


@pytest.mark.asyncio
async def test_fetch_excludes_unavailable_models(authed_client, db_session):
    """200 OK; a row flagged is_available=False never shows up, even matched by search."""
    prefix = f"Unavail{uuid4().hex[:8]}"
    visible = await create_record(db_session, DfEngineModelOptions, _model_option_data(name=f"{prefix}-visible"))
    hidden = await create_record(
        db_session, DfEngineModelOptions, _model_option_data(name=f"{prefix}-hidden", is_available=False)
    )

    resp = await authed_client.call("GET", URL, params={"search": prefix})
    names = [item["name"] for item in resp.json()["data"]["paginated"]]
    assert visible.name in names
    assert hidden.name not in names


@pytest.mark.asyncio
async def test_fetch_filter_by_type(authed_client, db_session):
    """200 OK; `type` restricts results to that one usage type only."""
    prefix = f"TypeFilter{uuid4().hex[:8]}"
    text_row = await create_record(
        db_session, DfEngineModelOptions, _model_option_data(name=f"{prefix}-text", type="text")
    )
    image_row = await create_record(
        db_session, DfEngineModelOptions, _model_option_data(name=f"{prefix}-image", type="image")
    )

    resp = await authed_client.call("GET", URL, params={"search": prefix, "type": "text"})
    names = [item["name"] for item in resp.json()["data"]["paginated"]]
    assert text_row.name in names
    assert image_row.name not in names


@pytest.mark.asyncio
async def test_fetch_search_is_a_prefix_match(authed_client, db_session):
    """200 OK; `search` matches names starting with it, not mid-string occurrences."""
    prefix = f"Search{uuid4().hex[:8]}"
    matching = await create_record(db_session, DfEngineModelOptions, _model_option_data(name=f"{prefix}-one"))
    await create_record(db_session, DfEngineModelOptions, _model_option_data(name=f"other-{prefix}"))

    resp = await authed_client.call("GET", URL, params={"search": prefix})
    names = [item["name"] for item in resp.json()["data"]["paginated"]]
    assert matching.name in names
    assert f"other-{prefix}" not in names


@pytest.mark.asyncio
async def test_fetch_filter_by_is_enabled(authed_client, db_session):
    """200 OK; `is_enabled` restricts to only-enabled or only-disabled rows."""
    prefix = f"EnabledFilter{uuid4().hex[:8]}"
    enabled_row = await create_record(
        db_session, DfEngineModelOptions, _model_option_data(name=f"{prefix}-on", is_enabled=True)
    )
    disabled_row = await create_record(
        db_session, DfEngineModelOptions, _model_option_data(name=f"{prefix}-off", is_enabled=False)
    )

    enabled_resp = await authed_client.call("GET", URL, params={"search": prefix, "is_enabled": True})
    enabled_names = [item["name"] for item in enabled_resp.json()["data"]["paginated"]]
    assert enabled_row.name in enabled_names
    assert disabled_row.name not in enabled_names

    disabled_resp = await authed_client.call("GET", URL, params={"search": prefix, "is_enabled": False})
    disabled_names = [item["name"] for item in disabled_resp.json()["data"]["paginated"]]
    assert disabled_row.name in disabled_names
    assert enabled_row.name not in disabled_names


@pytest.mark.asyncio
async def test_fetch_no_is_enabled_filter_returns_both(authed_client, db_session):
    """200 OK; omitting `is_enabled` includes both enabled and disabled rows."""
    prefix = f"NoFilter{uuid4().hex[:8]}"
    enabled_row = await create_record(
        db_session, DfEngineModelOptions, _model_option_data(name=f"{prefix}-on", is_enabled=True)
    )
    disabled_row = await create_record(
        db_session, DfEngineModelOptions, _model_option_data(name=f"{prefix}-off", is_enabled=False)
    )

    resp = await authed_client.call("GET", URL, params={"search": prefix})
    names = [item["name"] for item in resp.json()["data"]["paginated"]]
    assert enabled_row.name in names
    assert disabled_row.name in names


@pytest.mark.asyncio
async def test_response_shape_strips_id_and_keeps_uid(authed_client, db_session):
    """200 OK; internal `id` is stripped, `uid` is exposed, dates are formatted strings."""
    row = await create_record(db_session, DfEngineModelOptions, _model_option_data())

    resp = await authed_client.call("GET", URL, params={"search": row.name})
    item = resp.json()["data"]["paginated"][0]
    assert "id" not in item
    assert item["uid"] == row.uid
    assert isinstance(item["last_sync_at"], str)


@pytest.mark.asyncio
async def test_pagination_shape_and_total_data(authed_client, db_session):
    """200 OK; `totalData` reflects the full filtered count, `paginated` respects `itemsPerPage`."""
    prefix = f"Page{uuid4().hex[:8]}"
    await create_record(db_session, DfEngineModelOptions, _model_option_data(name=f"{prefix}-a"))
    await create_record(db_session, DfEngineModelOptions, _model_option_data(name=f"{prefix}-b"))

    resp = await authed_client.call("GET", URL, params={"search": prefix, "itemsPerPage": 1, "page": 1})
    body = resp.json()["data"]
    assert body["totalData"] == 2
    assert len(body["paginated"]) == 1

    page_two = await authed_client.call("GET", URL, params={"search": prefix, "itemsPerPage": 1, "page": 2})
    assert len(page_two.json()["data"]["paginated"]) == 1
    assert page_two.json()["data"]["paginated"][0]["name"] != resp.json()["data"]["paginated"][0]["name"]


@pytest.mark.asyncio
async def test_action_flags_available_enabled_not_main(authed_client, db_session):
    """200 OK; an available, enabled, non-main model can both be toggled and set main."""
    row = await create_record(db_session, DfEngineModelOptions, _model_option_data(is_enabled=True, is_main=False))

    resp = await authed_client.call("GET", URL, params={"search": row.name})
    item = resp.json()["data"]["paginated"][0]
    assert item["action"] == {"can_set_enabled": True, "can_set_main": True}


@pytest.mark.asyncio
async def test_action_flags_already_main_cannot_set_main_again(authed_client, db_session):
    """200 OK; a model that's already main shows can_set_main=False."""
    row = await create_record(db_session, DfEngineModelOptions, _model_option_data(is_enabled=True, is_main=True))

    resp = await authed_client.call("GET", URL, params={"search": row.name})
    item = resp.json()["data"]["paginated"][0]
    assert item["action"] == {"can_set_enabled": True, "can_set_main": False}


@pytest.mark.asyncio
async def test_action_flags_disabled_cannot_set_main(authed_client, db_session):
    """200 OK; a disabled model shows can_set_main=False (not eligible until enabled)."""
    row = await create_record(db_session, DfEngineModelOptions, _model_option_data(is_enabled=False))

    resp = await authed_client.call("GET", URL, params={"search": row.name})
    item = resp.json()["data"]["paginated"][0]
    assert item["action"] == {"can_set_enabled": True, "can_set_main": False}


@pytest.mark.asyncio
async def test_requires_auth(client):
    """401 when the request carries no bearer token."""
    resp = await client.call("GET", URL, raise_for_status=False)
    assert resp.status_code == 401
