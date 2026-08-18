import pytest
from uuid import uuid4
from middlewares.lang import resolve_message
from services.mysql.model import DfEnginePromptTemplates
from tests.helpers import create_record, expected_user, find_by_name

URL = "/api/prompt-management"


@pytest.mark.asyncio
async def test_update_full_replace(authed_client, db_session, user_id):
    """200 OK; PATCH replaces name/prompt/is_active and sets updated_by to the current user."""
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
    updater = await expected_user(db_session, user_id)
    new_name = f"Updated {uuid4().hex[:8]}"

    resp = await authed_client.call(
        "PATCH",
        f"{URL}/{row.uid}",
        json={
            "name": new_name,
            "prompt": "new prompt",
            "description": None,
            "is_active": True,
        },
    )
    assert resp.status_code == 200
    item = find_by_name(resp.json()["data"], new_name)
    assert item["prompt"] == "new prompt"
    assert item["is_active"] is True
    assert item["updater"] == updater


@pytest.mark.asyncio
async def test_update_deactivating_removes_it_from_the_list(authed_client, db_session, user_id):
    """200 OK; setting is_active False drops the template from the refreshed (active-only) list."""
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

    resp = await authed_client.call(
        "PATCH",
        f"{URL}/{row.uid}",
        json={"name": row.name, "prompt": row.prompt, "is_active": False},
    )
    assert resp.status_code == 200
    assert all(item["name"] != row.name for item in resp.json()["data"])


@pytest.mark.asyncio
async def test_update_renaming_to_its_own_current_name_succeeds(authed_client, db_session, user_id):
    """200 OK; renaming a template to its own current name doesn't trip the uniqueness conflict."""
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

    resp = await authed_client.call(
        "PATCH",
        f"{URL}/{row.uid}",
        json={"name": row.name, "prompt": "revised prompt", "is_active": True},
    )
    assert resp.status_code == 200
    item = find_by_name(resp.json()["data"], row.name)
    assert item["prompt"] == "revised prompt"


@pytest.mark.asyncio
async def test_update_unknown_uid_is_404(authed_client):
    """404 prompt_template_not_found when the path uid matches no template."""
    resp = await authed_client.call(
        "PATCH",
        f"{URL}/{uuid4()}",
        json={"name": "x", "prompt": "y"},
        raise_for_status=False,
    )
    assert resp.status_code == 404
    assert resp.json()["message"] == resolve_message("prompt_template_not_found", "en")


@pytest.mark.asyncio
async def test_update_rename_into_collision_is_409(authed_client, db_session, user_id):
    """409 when renaming a template to a name another template already has."""
    target = await create_record(
        db_session,
        DfEnginePromptTemplates,
        dict(
            uid=str(uuid4()),
            name=f"Prompt {uuid4().hex[:8]}",
            prompt="a prompt",
            created_by=int(user_id),
        ),
    )
    other = await create_record(
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
        "PATCH",
        f"{URL}/{other.uid}",
        json={"name": target.name, "prompt": "y"},
        raise_for_status=False,
    )
    assert resp.status_code == 409
    assert resp.json()["message"] == resolve_message("prompt_template_already_exists", "en")


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "overrides",
    [{"name": ""}, {"prompt": ""}],
    ids=["empty_name", "empty_prompt"],
)
async def test_update_validation_errors(authed_client, db_session, user_id, overrides):
    """422 for each individually invalid field: empty name, empty prompt."""
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
    payload = {"name": "valid name", "prompt": "valid prompt"}
    payload.update(overrides)
    resp = await authed_client.call("PATCH", f"{URL}/{row.uid}", json=payload, raise_for_status=False)
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_requires_auth(client, db_session, user_id):
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
    resp = await client.call(
        "PATCH",
        f"{URL}/{row.uid}",
        json={"name": row.name, "prompt": "y"},
        raise_for_status=False,
    )
    assert resp.status_code == 401
