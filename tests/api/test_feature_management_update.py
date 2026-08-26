import pytest
from uuid import uuid4
from sqlalchemy import select
from middlewares.lang import resolve_message
from services.mysql.model import DfEngineFeaturePromptMappings, DfEngineMenuFeatureMappings
from services.mysql.factory.df_engine_feature_prompt_mappings import DfEngineFeaturePromptMappingsFactory
from services.mysql.factory.df_engine_features import DfEngineFeaturesFactory
from services.mysql.factory.df_engine_menu_feature_mappings import DfEngineMenuFeatureMappingsFactory
from services.mysql.factory.df_engine_menus import DfEngineMenusFactory
from services.mysql.factory.df_engine_prompt_templates import DfEnginePromptTemplatesFactory
from services.redis import client as redis_client
from tests.helpers import find_by_name, response_names

URL = "/api/feature-management"


def _make_feature(user_id):
    return DfEngineFeaturesFactory.create(created_by=int(user_id), df_engine_feature_prompt_mapping=None)


def _make_template(user_id):
    return DfEnginePromptTemplatesFactory.create(prompt="a prompt", created_by=int(user_id))


@pytest.mark.asyncio
async def test_update_replaces_name_description_and_active(authed_client, user_id):
    """200 OK; PATCH is a full replace of name/description/is_active, not a partial diff."""
    feature = _make_feature(user_id)
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
async def test_update_add_and_remove_templates_in_one_call(authed_client, user_id):
    """200 OK; process diffs template_uids against existing mappings — unlinks removed, links added, in one call."""
    feature = _make_feature(user_id)
    kept = _make_template(user_id)
    removed = _make_template(user_id)
    added = _make_template(user_id)

    DfEngineFeaturePromptMappingsFactory.create(df_engine_features=feature, df_engine_prompt_templates=kept)
    DfEngineFeaturePromptMappingsFactory.create(df_engine_features=feature, df_engine_prompt_templates=removed)

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
    feature = _make_feature(user_id)
    template = _make_template(user_id)
    mapping = DfEngineFeaturePromptMappingsFactory.create(
        df_engine_features=feature, df_engine_prompt_templates=template
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
    await db_session.commit()
    still_present = (
        await db_session.execute(
            select(DfEngineFeaturePromptMappings).where(DfEngineFeaturePromptMappings.uid == mapping.uid)  # type: ignore
        )
    ).scalar_one_or_none()
    assert still_present is not None


@pytest.mark.asyncio
async def test_update_empty_template_uids_unlinks_everything(authed_client, user_id):
    """200 OK; passing an empty template_uids list unlinks every currently-mapped template."""
    feature = _make_feature(user_id)
    template = _make_template(user_id)
    DfEngineFeaturePromptMappingsFactory.create(df_engine_features=feature, df_engine_prompt_templates=template)

    resp = await authed_client.call(
        "PATCH",
        f"{URL}/{feature.uid}",
        json={"name": feature.name, "template_uids": []},
    )
    assert resp.status_code == 200
    item = find_by_name(resp.json()["data"], feature.name)
    assert item["templates"] == []


@pytest.mark.asyncio
async def test_update_deactivating_removes_its_menu_mappings(authed_client, db_session, user_id):
    """200 OK; setting is_active False deletes the feature's df_engine_menu_feature_mappings rows."""
    feature = _make_feature(user_id)
    menu = DfEngineMenusFactory.create(created_by=int(user_id), df_engine_menu_feature_mapping=None)
    DfEngineMenuFeatureMappingsFactory.create(df_engine_menus=menu, df_engine_features=feature)

    resp = await authed_client.call(
        "PATCH",
        f"{URL}/{feature.uid}",
        json={"name": feature.name, "is_active": False},
    )
    assert resp.status_code == 200
    await db_session.commit()

    remaining = (
        (
            await db_session.execute(
                select(DfEngineMenuFeatureMappings).where(DfEngineMenuFeatureMappings.feature_id == feature.id)  # type: ignore
            )
        )
        .scalars()
        .all()
    )
    assert remaining == []


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
async def test_update_unknown_template_uid_is_422(authed_client, user_id):
    """422; process rejects the whole update if a given template_uid doesn't exist."""
    feature = _make_feature(user_id)
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
async def test_update_rename_into_collision_is_409(authed_client, user_id):
    """409 when renaming a feature to a name another feature already has."""
    existing = _make_feature(user_id)
    other = _make_feature(user_id)

    resp = await authed_client.call(
        "PATCH",
        f"{URL}/{other.uid}",
        json={"name": existing.name},
        raise_for_status=False,
    )
    assert resp.status_code == 409
    assert resp.json()["message"] == resolve_message("feature_already_exists", "en")


@pytest.mark.asyncio
async def test_requires_auth(client, user_id):
    """401 when the request carries no bearer token."""
    feature = _make_feature(user_id)
    resp = await client.call(
        "PATCH",
        f"{URL}/{feature.uid}",
        json={"name": feature.name},
        raise_for_status=False,
    )
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_update_invalidates_the_detail_cache(authed_client, user_id):
    """200 OK; PATCH clears the cached detail so the next GET-by-uid reflects the new name, not the stale cache."""
    feature = _make_feature(user_id)
    detail_before = await authed_client.call("GET", f"{URL}/{feature.uid}")
    assert detail_before.json()["data"]["name"] == feature.name

    renamed = f"{feature.name}-v2"
    await authed_client.call("PATCH", f"{URL}/{feature.uid}", json={"name": renamed})

    detail_after = await authed_client.call("GET", f"{URL}/{feature.uid}")
    assert detail_after.json()["data"]["name"] == renamed


@pytest.mark.asyncio
async def test_update_invalidates_the_list_cache(authed_client, user_id):
    """200 OK; PATCH clears the cached list so a subsequent GET reflects the rename, not the stale cache."""
    feature = _make_feature(user_id)
    await authed_client.call("GET", URL)  # warm the unfiltered list cache
    assert await redis_client().exists("feature_management:list:all")

    renamed = f"{feature.name}-v2"
    await authed_client.call("PATCH", f"{URL}/{feature.uid}", json={"name": renamed})

    resp = await authed_client.call("GET", URL)
    found = response_names(resp.json())
    assert renamed in found
    assert feature.name not in found
