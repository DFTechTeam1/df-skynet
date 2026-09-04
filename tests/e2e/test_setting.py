"""End-to-end journey for DF Engine settings: the empty global document, the
first save (inserted, not logged), a no-op save (not logged), a real change
(logged with the diff), a per-project override, and the model-sync cascade that
nulls a setting when its main model goes unavailable.
"""

import pytest
from services.mysql.factory.df_engine_model_options import DfEngineModelOptionsFactory
from tests.helpers import available_model_rows, clear_setting_state, openrouter_item_from_row

SETTING_URL = "/api/setting"
LOGS_URL = "/api/setting/logs"
MODELS_URL = "/api/models"


@pytest.mark.asyncio
async def test_setting_lifecycle_journey(authed_client, db_session, mock_model_sync, project_with_class):
    project_uid, class_id, _ = project_with_class
    await clear_setting_state(db_session)
    model = DfEngineModelOptionsFactory.create(type="text", is_available=True, is_enabled=True, is_main=True)

    # 1. nothing saved yet — GET returns an empty document, no logs
    assert (await authed_client.call("GET", SETTING_URL)).json()["data"] == {}
    assert (await authed_client.call("GET", LOGS_URL)).json()["data"]["totalData"] == 0

    # 2. first save — rows inserted; the client sends the model UID, it is stored
    #    and returned as the name; not logged (no prior state)
    first_save = await authed_client.call(
        "POST", SETTING_URL, json={"admin_view": {"see_all_asset": True}, "enhancer_model": model.uid}
    )
    assert first_save.status_code == 200
    assert first_save.json()["data"]["enhancer_model"] == model.name
    assert (await authed_client.call("GET", LOGS_URL)).json()["data"]["totalData"] == 0

    # 3. no-op save — same values, no log
    await authed_client.call(
        "POST", SETTING_URL, json={"admin_view": {"see_all_asset": True}, "enhancer_model": model.uid}
    )
    assert (await authed_client.call("GET", LOGS_URL)).json()["data"]["totalData"] == 0

    # 4. real change — admin_view flipped; one log records the diff (names, not UIDs)
    await authed_client.call(
        "POST", SETTING_URL, json={"admin_view": {"see_all_asset": False}, "enhancer_model": model.uid}
    )
    logs = (await authed_client.call("GET", LOGS_URL)).json()["data"]
    assert logs["totalData"] == 1
    newest = logs["paginated"][0]
    assert newest["incoming_data"]["admin_view"] == {"see_all_asset": False}
    assert newest["previous_data"]["admin_view"] == {"see_all_asset": True}
    assert newest["incoming_data"]["enhancer_model"] == model.name
    assert newest["changed_fields"] == ["admin_view"]

    # 5. a per-project override — GET /setting/{uid} now serves it instead of the class fallback
    await authed_client.call(
        "POST",
        f"{SETTING_URL}/{project_uid}",
        json={
            "token_usage_limit": 3,
            "concurent_generations": 1,
            "compose_input_max_chars": 2000,
            "storyboard_prompt_chars": 2000,
            "max_scene_per_storyboard": 2000,
            "max_shot_per_scene": 2000,
        },
    )
    scoped = (await authed_client.call("GET", f"{SETTING_URL}/{project_uid}")).json()["data"]
    assert scoped["token_usage_limit"] == 3
    # the per-project save is not part of the global settings history
    assert (await authed_client.call("GET", LOGS_URL)).json()["data"]["totalData"] == 1

    # 6. sync drops the model from OpenRouter — it's a main model still referenced
    #    by the enhancer setting, so sync flags it unavailable AND nulls the setting.
    rows = await available_model_rows(db_session, "text")
    mock_model_sync.set(
        "/models?output_modalities=text",
        [openrouter_item_from_row(r) for r in rows if r.model_id != model.model_id],
    )
    assert (await authed_client.call("POST", MODELS_URL)).status_code == 200

    after_sync = await authed_client.call("GET", SETTING_URL)
    assert after_sync.json()["data"]["enhancer_model"] is None
    assert (await authed_client.call("GET", LOGS_URL)).json()["data"]["totalData"] == 2

    # 7. the now-unavailable model can no longer be picked again
    rejected = await authed_client.call("POST", SETTING_URL, json={"enhancer_model": model.uid}, raise_for_status=False)
    assert rejected.status_code == 422
