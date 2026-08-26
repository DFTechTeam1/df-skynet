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
from tests.helpers import response_names

URL = "/api/feature-management"


def _make_feature_with_mapping(user_id):
    feature = DfEngineFeaturesFactory.create(created_by=int(user_id), df_engine_feature_prompt_mapping=None)
    template = DfEnginePromptTemplatesFactory.create(prompt="a prompt", created_by=int(user_id))
    mapping = DfEngineFeaturePromptMappingsFactory.create(
        df_engine_features=feature, df_engine_prompt_templates=template
    )
    return feature, template, mapping


@pytest.mark.asyncio
async def test_delete_success(authed_client, user_id):
    """200 OK; deleted feature no longer appears in the refreshed list."""
    feature = DfEngineFeaturesFactory.create(created_by=int(user_id), df_engine_feature_prompt_mapping=None)
    resp = await authed_client.call("DELETE", f"{URL}/{feature.uid}")
    assert resp.status_code == 200
    assert feature.name not in response_names(resp.json())


@pytest.mark.asyncio
async def test_delete_cascades_to_mappings(authed_client, db_session, user_id):
    """200 OK; process deletes the feature's df_engine_feature_prompt_mappings rows too, not just the feature."""
    feature, template, mapping = _make_feature_with_mapping(user_id)
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
    feature = DfEngineFeaturesFactory.create(created_by=int(user_id), df_engine_feature_prompt_mapping=None)
    menu = DfEngineMenusFactory.create(created_by=int(user_id), df_engine_menu_feature_mapping=None)
    menu_mapping = DfEngineMenuFeatureMappingsFactory.create(df_engine_menus=menu, df_engine_features=feature)

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
async def test_delete_twice_is_404_on_the_second_call(authed_client, user_id):
    """First delete is 200 OK; repeating it is 404 feature_not_found since the row is already gone."""
    feature = DfEngineFeaturesFactory.create(created_by=int(user_id), df_engine_feature_prompt_mapping=None)
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
async def test_requires_auth(client, user_id):
    """401 when the request carries no bearer token."""
    feature = DfEngineFeaturesFactory.create(created_by=int(user_id), df_engine_feature_prompt_mapping=None)
    resp = await client.call("DELETE", f"{URL}/{feature.uid}", raise_for_status=False)
    assert resp.status_code == 401
