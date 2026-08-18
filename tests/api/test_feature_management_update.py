import pytest
from uuid import uuid4
from sqlalchemy import select
from middlewares.lang import resolve_message
from services.mysql.model import (
    DfEngineActionMappings,
    DfEngineActions,
    DfEnginePromptTemplates,
)
from tests.helpers import create_record, find_by_name

URL = "/api/feature-management"


async def _make_feature(db_session, user_id):
    return await create_record(
        db_session,
        DfEngineActions,
        dict(
            uid=str(uuid4()),
            name=f"Feature {uuid4().hex[:8]}",
            created_by=int(user_id),
        ),
    )


async def _make_template(db_session, user_id):
    return await create_record(
        db_session,
        DfEnginePromptTemplates,
        dict(
            uid=str(uuid4()),
            name=f"Prompt {uuid4().hex[:8]}",
            prompt="a prompt",
            created_by=int(user_id),
        ),
    )


@pytest.mark.asyncio
async def test_update_replaces_name_description_and_active(authed_client, db_session, user_id):
    """200 OK; PATCH is a full replace of name/description/is_active, not a partial diff."""
    feature = await _make_feature(db_session, user_id)
    renamed = f"{feature.name}-v2"

    resp = await authed_client.call(
        "PATCH",
        f"{URL}/{feature.uid}",
        json={"name": renamed, "description": "new desc", "is_active": False},
    )
    assert resp.status_code == 200
    item = find_by_name(resp.json()["data"], renamed)
    assert item["description"] == "new desc"
    assert item["is_active"] is False


@pytest.mark.asyncio
async def test_update_add_and_remove_templates_in_one_call(authed_client, db_session, user_id):
    """200 OK; process diffs template_uids against existing mappings — unlinks removed, links added, in one call."""
    feature = await _make_feature(db_session, user_id)
    kept = await _make_template(db_session, user_id)
    removed = await _make_template(db_session, user_id)
    added = await _make_template(db_session, user_id)

    await create_record(
        db_session,
        DfEngineActionMappings,
        dict(uid=str(uuid4()), action_id=feature.id, template_id=kept.id),
    )
    await create_record(
        db_session,
        DfEngineActionMappings,
        dict(uid=str(uuid4()), action_id=feature.id, template_id=removed.id),
    )

    resp = await authed_client.call(
        "PATCH",
        f"{URL}/{feature.uid}",
        json={
            "name": feature.name,
            "template_uids": [kept.uid, added.uid],
        },
    )
    assert resp.status_code == 200
    item = find_by_name(resp.json()["data"], feature.name)
    linked_uids = {t["template_uid"] for t in item["templates"]}
    assert linked_uids == {kept.uid, added.uid}


@pytest.mark.asyncio
async def test_update_preserves_mapping_uid_for_unchanged_template(authed_client, db_session, user_id):
    """200 OK; process leaves an unchanged mapping row untouched instead of deleting and recreating it."""
    feature = await _make_feature(db_session, user_id)
    template = await _make_template(db_session, user_id)
    mapping = await create_record(
        db_session,
        DfEngineActionMappings,
        dict(uid=str(uuid4()), action_id=feature.id, template_id=template.id),
    )

    resp = await authed_client.call(
        "PATCH",
        f"{URL}/{feature.uid}",
        json={"name": feature.name, "template_uids": [template.uid]},
    )
    assert resp.status_code == 200
    item = find_by_name(resp.json()["data"], feature.name)
    assert len(item["templates"]) == 1
    assert item["templates"][0]["template_uid"] == template.uid

    # Update left the linked template unchanged, so the join row itself
    # should never have been deleted and recreated — same query pattern as
    # the delete tests' cascade check, opening a fresh snapshot after the
    # HTTP call's own connection has committed.
    await db_session.commit()
    still_present = (
        await db_session.execute(select(DfEngineActionMappings).where(DfEngineActionMappings.uid == mapping.uid))
    ).scalar_one_or_none()
    assert still_present is not None


@pytest.mark.asyncio
async def test_update_empty_template_uids_unlinks_everything(authed_client, db_session, user_id):
    """200 OK; passing an empty template_uids list unlinks every currently-mapped template."""
    feature = await _make_feature(db_session, user_id)
    template = await _make_template(db_session, user_id)
    await create_record(
        db_session,
        DfEngineActionMappings,
        dict(uid=str(uuid4()), action_id=feature.id, template_id=template.id),
    )

    resp = await authed_client.call(
        "PATCH",
        f"{URL}/{feature.uid}",
        json={"name": feature.name, "template_uids": []},
    )
    assert resp.status_code == 200
    item = find_by_name(resp.json()["data"], feature.name)
    assert item["templates"] == []


@pytest.mark.asyncio
async def test_update_unknown_uid_is_404(authed_client):
    """404 feature_not_found when the path uid matches no feature."""
    resp = await authed_client.call(
        "PATCH",
        f"{URL}/{uuid4()}",
        json={"name": f"Ghost {uuid4().hex[:8]}"},
        raise_for_status=False,
    )
    assert resp.status_code == 404
    assert resp.json()["message"] == resolve_message("feature_not_found", "en")


@pytest.mark.asyncio
async def test_update_unknown_template_uid_is_422(authed_client, db_session, user_id):
    """422; process rejects the whole update if a given template_uid doesn't exist."""
    feature = await _make_feature(db_session, user_id)
    unknown_uid = str(uuid4())

    resp = await authed_client.call(
        "PATCH",
        f"{URL}/{feature.uid}",
        json={"name": feature.name, "template_uids": [unknown_uid]},
        raise_for_status=False,
    )
    assert resp.status_code == 422
    body = resp.json()
    assert body["message"] == resolve_message("feature_template_not_found", "en")
    assert body["error"]["template_uids.0"] == [resolve_message("prompt_template_not_found", "en")]


@pytest.mark.asyncio
async def test_update_rename_into_collision_is_409(authed_client, db_session, user_id):
    """409 when renaming a feature to a name another feature already has."""
    existing = await _make_feature(db_session, user_id)
    other = await _make_feature(db_session, user_id)

    resp = await authed_client.call(
        "PATCH",
        f"{URL}/{other.uid}",
        json={"name": existing.name},
        raise_for_status=False,
    )
    assert resp.status_code == 409
    assert resp.json()["message"] == resolve_message("feature_already_exists", "en")


@pytest.mark.asyncio
async def test_requires_auth(client, db_session, user_id):
    """401 when the request carries no bearer token."""
    feature = await _make_feature(db_session, user_id)
    resp = await client.call(
        "PATCH",
        f"{URL}/{feature.uid}",
        json={"name": feature.name},
        raise_for_status=False,
    )
    assert resp.status_code == 401
