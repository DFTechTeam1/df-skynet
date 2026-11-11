import pytest
from uuid import uuid4
from middlewares.lang import resolve_message
from services.dto import ConnectionContext
from services.dto.asynced.admin_settings import get_menu
from services.mysql.factory.df_engine_feature_prompt_mappings import DfEngineFeaturePromptMappingsFactory
from services.mysql.factory.df_engine_features import DfEngineFeaturesFactory
from services.mysql.factory.df_engine_menu_feature_mappings import DfEngineMenuFeatureMappingsFactory
from services.mysql.factory.df_engine_menus import DfEngineMenusFactory
from services.mysql.factory.df_engine_prompt_template_references import DfEnginePromptTemplateReferencesFactory
from services.mysql.factory.df_engine_prompt_templates import DfEnginePromptTemplatesFactory
from services.redis import CacheKeys, client as redis_client
from tests.helpers import find_by_name

URL = "/api/prompt-management"


def _template(user_id, **kw):
    return DfEnginePromptTemplatesFactory.create(created_by=int(user_id), **kw)


def _payload(name=None, refs=(), **kw):
    return {
        "name": name or f"T {uuid4().hex[:8]}",
        "prompt": "p " + " ".join(str(r) for r in refs),
        "template_references": [str(r) for r in refs],
        **kw,
    }


@pytest.mark.asyncio
async def test_detail_defaults_to_empty_references(authed_client, user_id):
    """200 OK; a template without references returns template_references == []."""
    row = _template(user_id)
    resp = await authed_client.call("GET", f"{URL}/{row.uid}")
    assert resp.json()["data"]["template_references"] == []


@pytest.mark.asyncio
async def test_create_with_references_and_dedupe(authed_client, user_id):
    """200 OK; references are stored once even if sent twice, and returned as uid + name."""
    ref = _template(user_id)
    payload = _payload(refs=[ref.uid, ref.uid])
    resp = await authed_client.call("POST", URL, json=payload)
    item = find_by_name(resp.json()["data"], payload["name"])
    assert item["template_references"] == [{"uid": ref.uid, "name": ref.name}]

    detail = await authed_client.call("GET", f"{URL}/{item['uid']}")
    assert detail.json()["data"]["template_references"] == [{"uid": ref.uid, "name": ref.name}]


@pytest.mark.asyncio
async def test_create_unknown_reference_is_404(authed_client):
    """404 prompt_template_not_found when a referenced uid does not exist."""
    resp = await authed_client.call("POST", URL, json=_payload(refs=[uuid4()]), raise_for_status=False)
    assert resp.status_code == 404
    assert resp.json()["message"] == resolve_message("prompt_template_not_found", "en")


@pytest.mark.asyncio
async def test_update_replaces_references(authed_client, user_id):
    """200 OK; PATCH swaps the reference set: kept ones stay, removed ones go, new ones are added."""
    a, b, c = _template(user_id), _template(user_id), _template(user_id)
    main = _template(user_id)
    DfEnginePromptTemplateReferencesFactory.create(main_template_id=main.id, reference_id=a.id)
    DfEnginePromptTemplateReferencesFactory.create(main_template_id=main.id, reference_id=b.id)

    resp = await authed_client.call("PATCH", f"{URL}/{main.uid}", json=_payload(main.name, refs=[b.uid, c.uid]))
    item = find_by_name(resp.json()["data"], main.name)
    assert {r["uid"] for r in item["template_references"]} == {b.uid, c.uid}

    clear = await authed_client.call("PATCH", f"{URL}/{main.uid}", json=_payload(main.name))
    assert find_by_name(clear.json()["data"], main.name)["template_references"] == []


@pytest.mark.asyncio
async def test_update_self_reference_is_rejected(authed_client, user_id):
    """422 prompt_template_self_reference when a template references itself."""
    main = _template(user_id)
    resp = await authed_client.call(
        "PATCH", f"{URL}/{main.uid}", json=_payload(main.name, refs=[main.uid]), raise_for_status=False
    )
    assert resp.status_code in (400, 422)
    assert resp.json()["message"] == resolve_message("prompt_template_self_reference", "en")


@pytest.mark.asyncio
async def test_update_renamed_reference_refreshes_referencing_cache(authed_client, user_id):
    """200 OK; renaming a referenced template shows the new name on templates that reference it."""
    ref, main = _template(user_id), _template(user_id)
    DfEnginePromptTemplateReferencesFactory.create(main_template_id=main.id, reference_id=ref.id)
    await authed_client.call("GET", f"{URL}/{main.uid}")  # warm detail cache

    new_name = f"Renamed {uuid4().hex[:8]}"
    await authed_client.call("PATCH", f"{URL}/{ref.uid}", json=_payload(new_name))
    detail = await authed_client.call("GET", f"{URL}/{main.uid}")
    assert detail.json()["data"]["template_references"] == [{"uid": ref.uid, "name": new_name}]


@pytest.mark.asyncio
async def test_delete_referenced_template_drops_the_relation(authed_client, user_id):
    """200 OK; deleting a referenced template cascades away the relation on the referencing template."""
    ref, main = _template(user_id), _template(user_id)
    DfEnginePromptTemplateReferencesFactory.create(main_template_id=main.id, reference_id=ref.id)
    await authed_client.call("GET", f"{URL}/{main.uid}")  # warm detail cache

    resp = await authed_client.call("DELETE", f"{URL}/{ref.uid}")
    assert resp.status_code == 200
    assert find_by_name(resp.json()["data"], main.name)["template_references"] == []
    detail = await authed_client.call("GET", f"{URL}/{main.uid}")
    assert detail.json()["data"]["template_references"] == []


@pytest.mark.asyncio
async def test_menu_injection_includes_references_deduped(db_session, user_id):
    """Feature maps A and B, A references B (and C): injected prompts are [A, B, C] — B only once."""
    a, b, c = _template(user_id), _template(user_id), _template(user_id)
    DfEnginePromptTemplateReferencesFactory.create(main_template_id=a.id, reference_id=b.id)
    DfEnginePromptTemplateReferencesFactory.create(main_template_id=a.id, reference_id=c.id)
    menu = DfEngineMenusFactory.create(created_by=int(user_id), df_engine_menu_feature_mapping=None)
    feature = DfEngineFeaturesFactory.create(created_by=int(user_id), df_engine_feature_prompt_mapping=None)
    DfEngineMenuFeatureMappingsFactory.create(df_engine_menus=menu, df_engine_features=feature)
    for t in (a, b):
        DfEngineFeaturePromptMappingsFactory.create(df_engine_features=feature, df_engine_prompt_templates=t)

    ctx = ConnectionContext(db_session, redis_client(), CacheKeys())
    data = await get_menu(ctx, int(user_id), menu_uid=menu.uid, feature_uid=feature.uid)
    assert [t["uid"] for t in data["features"][0]["prompt_templates"]] == [a.uid, b.uid, c.uid]
