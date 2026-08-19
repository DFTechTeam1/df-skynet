import pytest
from uuid import uuid4
from sqlalchemy import select
from middlewares.lang import resolve_message
from services.mysql.model import (
    DfEngineFeaturePromptMappings,
    DfEngineFeatures,
    DfEngineMenuFeatureMappings,
    DfEngineMenus,
    DfEnginePromptTemplates,
)
from tests.helpers import create_record, response_names

URL = "/api/feature-management"


async def _make_feature_with_mapping(db_session, user_id):
    feature = await create_record(
        db_session,
        DfEngineFeatures,
        dict(
            uid=str(uuid4()),
            name=f"Feature {uuid4().hex[:8]}",
            created_by=int(user_id),
        ),
    )
    template = await create_record(
        db_session,
        DfEnginePromptTemplates,
        dict(
            uid=str(uuid4()),
            name=f"Prompt {uuid4().hex[:8]}",
            prompt="a prompt",
            created_by=int(user_id),
        ),
    )
    mapping = await create_record(
        db_session,
        DfEngineFeaturePromptMappings,
        dict(uid=str(uuid4()), feature_id=feature.id, template_id=template.id),
    )
    return feature, template, mapping


@pytest.mark.asyncio
async def test_delete_success(authed_client, db_session, user_id):
    """200 OK; deleted feature no longer appears in the refreshed list."""
    feature = await create_record(
        db_session,
        DfEngineFeatures,
        dict(
            uid=str(uuid4()),
            name=f"Feature {uuid4().hex[:8]}",
            created_by=int(user_id),
        ),
    )
    resp = await authed_client.call("DELETE", f"{URL}/{feature.uid}")
    assert resp.status_code == 200
    assert feature.name not in response_names(resp.json())


@pytest.mark.asyncio
async def test_delete_cascades_to_mappings(authed_client, db_session, user_id):
    """200 OK; process deletes the feature's df_engine_feature_prompt_mappings rows too, not just the feature."""
    feature, template, mapping = await _make_feature_with_mapping(db_session, user_id)
    resp = await authed_client.call("DELETE", f"{URL}/{feature.uid}")
    assert resp.status_code == 200
    await db_session.commit()

    remaining = (
        await db_session.execute(
            select(DfEngineFeaturePromptMappings).where(DfEngineFeaturePromptMappings.uid == mapping.uid)  # type: ignore
        )
    ).scalar_one_or_none()
    assert remaining is None


@pytest.mark.asyncio
async def test_delete_also_cascades_menu_feature_mappings(authed_client, db_session, user_id):
    """200 OK; process also deletes the feature's df_engine_menu_feature_mappings rows (its menu links)."""
    feature = await create_record(
        db_session,
        DfEngineFeatures,
        dict(
            uid=str(uuid4()),
            name=f"Feature {uuid4().hex[:8]}",
            created_by=int(user_id),
        ),
    )
    menu = await create_record(
        db_session,
        DfEngineMenus,
        dict(
            uid=str(uuid4()),
            name=f"Menu {uuid4().hex[:8]}",
            created_by=int(user_id),
        ),
    )
    menu_mapping = await create_record(
        db_session,
        DfEngineMenuFeatureMappings,
        dict(uid=str(uuid4()), feature_id=feature.id, menu_id=menu.id),
    )

    resp = await authed_client.call("DELETE", f"{URL}/{feature.uid}")
    assert resp.status_code == 200
    await db_session.commit()

    remaining = (
        await db_session.execute(
            select(DfEngineMenuFeatureMappings).where(DfEngineMenuFeatureMappings.uid == menu_mapping.uid)  # type: ignore
        )
    ).scalar_one_or_none()
    assert remaining is None


@pytest.mark.asyncio
async def test_delete_twice_is_404_on_the_second_call(authed_client, db_session, user_id):
    """First delete is 200 OK; repeating it is 404 feature_not_found since the row is already gone."""
    feature = await create_record(
        db_session,
        DfEngineFeatures,
        dict(
            uid=str(uuid4()),
            name=f"Feature {uuid4().hex[:8]}",
            created_by=int(user_id),
        ),
    )
    first = await authed_client.call("DELETE", f"{URL}/{feature.uid}")
    assert first.status_code == 200
    second = await authed_client.call("DELETE", f"{URL}/{feature.uid}", raise_for_status=False)
    assert second.status_code == 404
    assert second.json()["message"] == resolve_message("feature_not_found", "en")


@pytest.mark.asyncio
async def test_delete_unknown_uid_is_404(authed_client):
    """404 feature_not_found when the uid matches no feature."""
    resp = await authed_client.call("DELETE", f"{URL}/{uuid4()}", raise_for_status=False)
    assert resp.status_code == 404
    assert resp.json()["message"] == resolve_message("feature_not_found", "en")


@pytest.mark.asyncio
async def test_requires_auth(client, db_session, user_id):
    """401 when the request carries no bearer token."""
    feature = await create_record(
        db_session,
        DfEngineFeatures,
        dict(
            uid=str(uuid4()),
            name=f"Feature {uuid4().hex[:8]}",
            created_by=int(user_id),
        ),
    )
    resp = await client.call("DELETE", f"{URL}/{feature.uid}", raise_for_status=False)
    assert resp.status_code == 401
