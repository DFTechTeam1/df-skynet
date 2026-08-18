import pytest
from uuid import uuid4
from middlewares.lang import resolve_message
from services.mysql.model import DfEnginePromptTemplates
from tests.helpers import create_record, expected_user, find_by_name

URL = "/api/prompt-management"


@pytest.mark.asyncio
async def test_create_success_returns_full_refreshed_list(authed_client):
    """200 OK; response body is the refreshed template list, with the new template's fields as given."""
    name = f"Create Test {uuid4().hex[:8]}"
    resp = await authed_client.call(
        "POST",
        URL,
        json={
            "name": name,
            "prompt": "a prompt",
            "description": "a desc",
            "is_active": True,
        },
    )
    assert resp.status_code == 200
    item = find_by_name(resp.json()["data"], name)
    assert item["prompt"] == "a prompt"
    assert item["description"] == "a desc"
    assert item["is_active"] is True


@pytest.mark.asyncio
async def test_create_defaults_is_active_true_and_description_none(authed_client):
    """200 OK; omitting is_active/description falls back to active and null description."""
    name = f"Create Defaults {uuid4().hex[:8]}"
    resp = await authed_client.call("POST", URL, json={"name": name, "prompt": "a prompt"})
    assert resp.status_code == 200
    item = find_by_name(resp.json()["data"], name)
    assert item["is_active"] is True
    assert item["description"] is None


@pytest.mark.asyncio
async def test_create_sets_creater_to_authenticated_user(authed_client, db_session, user_id):
    """200 OK; created_by comes from the bearer token's user, not from the request body."""
    name = f"Create Creater {uuid4().hex[:8]}"
    creater = await expected_user(db_session, user_id)

    resp = await authed_client.call("POST", URL, json={"name": name, "prompt": "a prompt"})
    item = find_by_name(resp.json()["data"], name)
    assert item["creater"] == creater
    assert item["updater"] is None


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "overrides",
    [
        {"name": ""},
        {"name": "x" * 256},
        {"prompt": ""},
        {"prompt": "x" * 16_001},
        {"description": ""},
    ],
    ids=[
        "empty_name",
        "oversized_name",
        "empty_prompt",
        "oversized_prompt",
        "empty_description",
    ],
)
async def test_create_validation_errors(authed_client, overrides):
    """422 for each individually invalid field: empty/oversized name, empty/oversized prompt, empty description."""
    payload = {"name": f"Invalid {uuid4().hex[:8]}", "prompt": "a prompt"}
    payload.update(overrides)
    resp = await authed_client.call("POST", URL, json=payload, raise_for_status=False)
    assert resp.status_code == 422


@pytest.mark.asyncio
@pytest.mark.parametrize("missing", ["name", "prompt"])
async def test_create_missing_required_field(authed_client, missing):
    """422 when either required field (`name` or `prompt`) is omitted entirely."""
    payload = {"name": f"Invalid {uuid4().hex[:8]}", "prompt": "a prompt"}
    del payload[missing]
    resp = await authed_client.call("POST", URL, json=payload, raise_for_status=False)
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_create_duplicate_name_conflict(authed_client, db_session, user_id):
    """409 when `name` already belongs to another prompt template."""
    existing = await create_record(
        db_session,
        DfEnginePromptTemplates,
        dict(
            uid=str(uuid4()),
            name=f"Prompt {uuid4().hex[:8]}",
            prompt="a prompt",
            created_by=int(user_id),
        ),
    )
    resp = await authed_client.call(
        "POST",
        URL,
        json={"name": existing.name, "prompt": "a prompt"},
        raise_for_status=False,
    )
    assert resp.status_code == 409
    assert resp.json()["message"] == resolve_message("prompt_template_already_exists", "en")


@pytest.mark.asyncio
async def test_requires_auth(client):
    """401 when the request carries no bearer token."""
    resp = await client.call(
        "POST",
        URL,
        json={"name": f"Unauth {uuid4().hex[:8]}", "prompt": "a prompt"},
        raise_for_status=False,
    )
    assert resp.status_code == 401
