import pytest
from uuid import uuid4
from sqlalchemy import select
from middlewares.lang import resolve_message
from services.mysql.model import DfEngineMenuFeatureMappings
from services.mysql.factory.df_engine_features import DfEngineFeaturesFactory
from services.mysql.factory.df_engine_menu_feature_mappings import DfEngineMenuFeatureMappingsFactory
from services.mysql.factory.df_engine_menus import DfEngineMenusFactory
from services.redis import client as redis_client
from tests.helpers import response_names

URL = "/api/menu-management"


def _make_menu_with_mapping(user_id):
    menu = DfEngineMenusFactory.create(created_by=int(user_id), df_engine_menu_feature_mapping=None)
    feature = DfEngineFeaturesFactory.create(created_by=int(user_id), df_engine_feature_prompt_mapping=None)
    mapping = DfEngineMenuFeatureMappingsFactory.create(df_engine_menus=menu, df_engine_features=feature)
    return menu, feature, mapping


@pytest.mark.asyncio
async def test_delete_success(authed_client, user_id):
    """200 OK; deleted menu no longer appears in the refreshed list."""
    menu = DfEngineMenusFactory.create(created_by=int(user_id), df_engine_menu_feature_mapping=None)
    resp = await authed_client.call("DELETE", f"{URL}/{menu.uid}")
    assert resp.status_code == 200
    assert menu.name not in response_names(resp.json())


@pytest.mark.asyncio
async def test_delete_cascades_to_mappings(authed_client, db_session, user_id):
    """200 OK; process deletes the menu's df_engine_menu_feature_mappings rows too, not just the menu."""
    menu, feature, mapping = _make_menu_with_mapping(user_id)
    resp = await authed_client.call("DELETE", f"{URL}/{menu.uid}")
    assert resp.status_code == 200
    await db_session.commit()

    remaining = (
        await db_session.execute(
            select(DfEngineMenuFeatureMappings).where(DfEngineMenuFeatureMappings.uid == mapping.uid)  # type: ignore
        )
    ).scalar_one_or_none()
    assert remaining is None


@pytest.mark.asyncio
async def test_delete_twice_is_404_on_the_second_call(authed_client, user_id):
    """First delete is 200 OK; repeating it is 404 menu_not_found since the row is already gone."""
    menu = DfEngineMenusFactory.create(created_by=int(user_id), df_engine_menu_feature_mapping=None)
    first = await authed_client.call("DELETE", f"{URL}/{menu.uid}")
    assert first.status_code == 200
    second = await authed_client.call("DELETE", f"{URL}/{menu.uid}", raise_for_status=False)
    assert second.status_code == 404
    assert second.json()["message"] == resolve_message("menu_not_found", "en")


@pytest.mark.asyncio
async def test_delete_unknown_uid_is_404(authed_client):
    """404 menu_not_found when the uid matches no menu."""
    resp = await authed_client.call("DELETE", f"{URL}/{uuid4()}", raise_for_status=False)
    assert resp.status_code == 404
    assert resp.json()["message"] == resolve_message("menu_not_found", "en")


@pytest.mark.asyncio
async def test_requires_auth(client, user_id):
    """401 when the request carries no bearer token."""
    menu = DfEngineMenusFactory.create(created_by=int(user_id), df_engine_menu_feature_mapping=None)
    resp = await client.call("DELETE", f"{URL}/{menu.uid}", raise_for_status=False)
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_delete_invalidates_the_list_cache(authed_client, user_id):
    """200 OK; DELETE clears the cached list so a subsequent GET no longer shows the deleted menu."""
    menu = DfEngineMenusFactory.create(created_by=int(user_id), df_engine_menu_feature_mapping=None)
    warm = await authed_client.call("GET", URL)
    assert menu.name in response_names(warm.json())
    assert await redis_client().exists("menu_management:list:all")

    await authed_client.call("DELETE", f"{URL}/{menu.uid}")

    resp = await authed_client.call("GET", URL)
    assert menu.name not in response_names(resp.json())
