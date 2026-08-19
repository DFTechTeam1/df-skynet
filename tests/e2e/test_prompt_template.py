import pytest
from uuid import uuid4
from services.mysql.model import (
    DfEngineFeaturePromptMappings,
    DfEngineFeatures,
    DfEnginePromptTemplates,
)
from tests.helpers import create_record, response_names


URL = "/api/prompt-management"


@pytest.mark.asyncio
async def test_full_crud_lifecycle(authed_client):
    """Walks create -> search -> update (twice) -> list -> delete for one template, checking each response reflects the latest state."""
    name = f"Journey {uuid4().hex[:8]}"

    # 1. create
    create_resp = await authed_client.call("POST", URL, json={"name": name, "prompt": "v1 prompt"})
    assert create_resp.status_code == 200
    assert name in response_names(create_resp.json())
    created = next(t for t in create_resp.json()["data"] if t["name"] == name)
    uid = created["uid"]

    # 2. search finds it by its own name
    search_resp = await authed_client.call("GET", URL, params={"name": name})
    assert name in response_names(search_resp.json())

    # 3. update (rename + new prompt) — first sequential write inside this
    # journey after the create above
    renamed = f"{name}-v2"
    update_resp = await authed_client.call(
        "PATCH",
        f"{URL}/{uid}",
        json={"name": renamed, "prompt": "v2 prompt", "is_active": True},
    )
    assert update_resp.status_code == 200
    assert renamed in response_names(update_resp.json())
    assert name not in response_names(update_resp.json())

    # 4. a second sequential update, proving multiple writes compose correctly
    renamed_again = f"{name}-v3"
    update_resp_2 = await authed_client.call(
        "PATCH",
        f"{URL}/{uid}",
        json={"name": renamed_again, "prompt": "v3 prompt", "is_active": True},
    )
    assert renamed_again in response_names(update_resp_2.json())

    # 5. list reflects the latest state
    list_resp = await authed_client.call("GET", URL)
    assert renamed_again in response_names(list_resp.json())
    assert renamed not in response_names(list_resp.json())

    # 6. delete
    delete_resp = await authed_client.call("DELETE", f"{URL}/{uid}")
    assert delete_resp.status_code == 200
    assert renamed_again not in response_names(delete_resp.json())

    # 7. confirmed gone on a fresh list too
    final_list = await authed_client.call("GET", URL)
    assert renamed_again not in response_names(final_list.json())


@pytest.mark.asyncio
async def test_duplicate_name_conflict_from_create_and_update(authed_client):
    """409 from both create and rename-via-update when the target name is already taken, and a failed rename leaves the original name intact."""
    suffix = uuid4().hex[:8]
    alpha_name = f"Alpha-{suffix}"
    beta_name = f"Beta-{suffix}"

    alpha_resp = await authed_client.call("POST", URL, json={"name": alpha_name, "prompt": "p"})
    assert alpha_resp.status_code == 200

    beta_resp = await authed_client.call("POST", URL, json={"name": beta_name, "prompt": "p"})
    assert beta_resp.status_code == 200
    beta_uid = next(t for t in beta_resp.json()["data"] if t["name"] == beta_name)["uid"]

    # renaming beta to alpha's name conflicts
    rename_conflict = await authed_client.call(
        "PATCH",
        f"{URL}/{beta_uid}",
        json={"name": alpha_name, "prompt": "p"},
        raise_for_status=False,
    )
    assert rename_conflict.status_code == 409

    # creating a second "alpha" from scratch conflicts too — same guard, different trigger
    create_conflict = await authed_client.call(
        "POST", URL, json={"name": alpha_name, "prompt": "p"}, raise_for_status=False
    )
    assert create_conflict.status_code == 409

    # beta was never actually renamed by the failed attempt
    list_resp = await authed_client.call("GET", URL)
    assert beta_name in response_names(list_resp.json())


@pytest.mark.asyncio
async def test_delete_blocked_then_succeeds_after_unmapping(authed_client, db_session, user_id):
    """409 prompt_template_in_use while mapped to a feature; delete succeeds once the mapping row is removed out-of-band."""
    row = await create_record(
        db_session,
        DfEnginePromptTemplates,
        dict(
            uid=str(uuid4()),
            name=f"Journey {uuid4().hex[:8]}",
            prompt="a prompt",
            created_by=int(user_id),
        ),
    )

    feature = await create_record(
        db_session,
        DfEngineFeatures,
        dict(
            uid=str(uuid4()),
            name=f"Feature {uuid4().hex[:8]}",
            created_by=int(user_id),
        ),
    )
    mapping = await create_record(
        db_session,
        DfEngineFeaturePromptMappings,
        dict(uid=str(uuid4()), feature_id=feature.id, template_id=row.id),
    )

    blocked = await authed_client.call("DELETE", f"{URL}/{row.uid}", raise_for_status=False)
    assert blocked.status_code == 409
    # error responses go through URL_handler's {message, error} shape, not
    # the Response {message, data} envelope — no "data" key to inspect here.
    assert "data" not in blocked.json()

    # still present, since the delete failed
    list_resp = await authed_client.call("GET", URL)
    assert row.name in response_names(list_resp.json())

    # an admin removes the dependency out-of-band (no unmap API exists yet)
    await db_session.delete(mapping)
    await db_session.commit()

    unblocked = await authed_client.call("DELETE", f"{URL}/{row.uid}")
    assert unblocked.status_code == 200
    assert row.name not in response_names(unblocked.json())


@pytest.mark.asyncio
async def test_search_and_active_filter_compose_correctly(authed_client):
    """200 OK; name search returns only active-matching templates, excluding an inactive one with a matching prefix."""
    prefix = f"Report{uuid4().hex[:8]}"
    active_a = f"{prefix}-A"
    active_b = f"{prefix}-B"
    inactive_c = f"{prefix}-C"

    await authed_client.call("POST", URL, json={"name": active_a, "prompt": "p", "is_active": True})
    await authed_client.call("POST", URL, json={"name": active_b, "prompt": "p", "is_active": True})
    await authed_client.call("POST", URL, json={"name": inactive_c, "prompt": "p", "is_active": False})

    search_resp = await authed_client.call("GET", URL, params={"name": prefix})
    found = response_names(search_resp.json())

    assert active_a in found
    assert active_b in found
    assert inactive_c not in found


@pytest.mark.asyncio
async def test_clone_template_under_a_new_name(authed_client, db_session, user_id):
    """200 OK; cloning (same prompt content, new name) succeeds since only `name`, not `prompt`, must be unique."""
    original = await create_record(
        db_session,
        DfEnginePromptTemplates,
        dict(
            uid=str(uuid4()),
            name=f"Original {uuid4().hex[:8]}",
            prompt="shared body",
            created_by=int(user_id),
        ),
    )
    clone_name = f"{original.name}-clone"

    clone_resp = await authed_client.call("POST", URL, json={"name": clone_name, "prompt": original.prompt})
    assert clone_resp.status_code == 200
    found = response_names(clone_resp.json())
    assert original.name in found
    assert clone_name in found
