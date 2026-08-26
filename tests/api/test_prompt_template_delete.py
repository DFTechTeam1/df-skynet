import pytest
from uuid import uuid4
from middlewares.lang import resolve_message
from services.mysql.factory.df_engine_feature_prompt_mappings import DfEngineFeaturePromptMappingsFactory
from services.mysql.factory.df_engine_features import DfEngineFeaturesFactory
from services.mysql.factory.df_engine_prompt_templates import DfEnginePromptTemplatesFactory
from services.redis import client as redis_client
from tests.helpers import response_names

URL = "/api/prompt-management"


@pytest.mark.asyncio
async def test_delete_success(authed_client, user_id):
    """200 OK; deleted template no longer appears in the refreshed list."""
    row = DfEnginePromptTemplatesFactory.create(prompt="a prompt", created_by=int(user_id))
    resp = await authed_client.call("DELETE", f"{URL}/{row.uid}")
    assert resp.status_code == 200
    assert row.name not in response_names(resp.json())


@pytest.mark.asyncio
async def test_delete_twice_is_404_on_the_second_call(authed_client, user_id):
    """First delete is 200 OK; repeating it is 404 prompt_template_not_found since the row is already gone."""
    row = DfEnginePromptTemplatesFactory.create(prompt="a prompt", created_by=int(user_id))
    first = await authed_client.call("DELETE", f"{URL}/{row.uid}")
    assert first.status_code == 200
    second = await authed_client.call("DELETE", f"{URL}/{row.uid}", raise_for_status=False)
    assert second.status_code == 404
    assert second.json()["message"] == resolve_message("prompt_template_not_found", "en")


@pytest.mark.asyncio
async def test_delete_unknown_uid_is_404(authed_client):
    """404 prompt_template_not_found when the uid matches no template."""
    resp = await authed_client.call("DELETE", f"{URL}/{uuid4()}", raise_for_status=False)
    assert resp.status_code == 404
    assert resp.json()["message"] == resolve_message("prompt_template_not_found", "en")


@pytest.mark.asyncio
async def test_delete_blocked_while_mapped_to_a_feature(authed_client, user_id):
    """409 prompt_template_in_use when the template is still referenced by a df_engine_feature_prompt_mappings row; template stays in the list."""
    row = DfEnginePromptTemplatesFactory.create(prompt="a prompt", created_by=int(user_id))
    feature = DfEngineFeaturesFactory.create(created_by=int(user_id), df_engine_feature_prompt_mapping=None)
    DfEngineFeaturePromptMappingsFactory.create(df_engine_features=feature, df_engine_prompt_templates=row)

    resp = await authed_client.call("DELETE", f"{URL}/{row.uid}", raise_for_status=False)
    assert resp.status_code == 409
    assert resp.json()["message"] == resolve_message("prompt_template_in_use", "en")
    assert "data" not in resp.json()

    still_present = await authed_client.call("GET", URL)
    assert row.name in response_names(still_present.json())


@pytest.mark.asyncio
async def test_requires_auth(client, user_id):
    """401 when the request carries no bearer token."""
    row = DfEnginePromptTemplatesFactory.create(prompt="a prompt", created_by=int(user_id))
    resp = await client.call("DELETE", f"{URL}/{row.uid}", raise_for_status=False)
    assert resp.status_code == 401


# --- localization ------------------------------------------------------------


@pytest.mark.asyncio
async def test_not_found_message_respects_accept_language(authed_client):
    """404; the not_found message text is localized per the Accept-Language header, differing between en and id."""
    unknown_uid = uuid4()

    en_resp = await authed_client.call(
        "DELETE",
        f"{URL}/{unknown_uid}",
        headers={"Accept-Language": "en"},
        raise_for_status=False,
    )
    id_resp = await authed_client.call(
        "DELETE",
        f"{URL}/{unknown_uid}",
        headers={"Accept-Language": "id"},
        raise_for_status=False,
    )

    assert en_resp.json()["message"] == resolve_message("prompt_template_not_found", "en")
    assert id_resp.json()["message"] == resolve_message("prompt_template_not_found", "id")
    assert en_resp.json()["message"] != id_resp.json()["message"]


@pytest.mark.asyncio
async def test_delete_invalidates_the_list_cache(authed_client, user_id):
    """200 OK; DELETE clears the cached list so a subsequent GET no longer shows the deleted template."""
    row = DfEnginePromptTemplatesFactory.create(prompt="a prompt", created_by=int(user_id))
    warm = await authed_client.call("GET", URL)
    assert row.name in response_names(warm.json())
    assert await redis_client().exists("prompt_template:list:all")

    await authed_client.call("DELETE", f"{URL}/{row.uid}")

    resp = await authed_client.call("GET", URL)
    assert row.name not in response_names(resp.json())
