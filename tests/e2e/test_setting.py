"""End-to-end journey for DF Engine admin settings: initial fetch, first save
(inserted, not logged — nothing to diff against), a no-op save (not logged), a
real change (logged with the actual diff), and the enhancer-model validation +
the sync cascade that nulls a setting when its main model goes unavailable.
"""

import pytest
from typing import Any
from services.mysql.factory.df_engine_model_options import DfEngineModelOptionsFactory
from tests.helpers import available_model_rows, clear_setting_state, openrouter_item_from_row

SETTING_URL = "/api/setting"
LOGS_URL = "/api/setting/logs"
MODELS_URL = "/api/models"


def _base_payload(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "admin_view": {"see_all_asset": True},
        "limit": {"generate_per_min": 0, "enhance_per_min": 0},
        "spend_ceiling": {"daily_ceiling_global_user": 0, "daily_ceiling_per_user": 0},
        "storyboard": {"max_storyboard_char": 4000, "max_scene_per_storyboard": 100, "max_shot_per_scene": 100},
        "compose_input": {"max_prompt_char": 4000},
        "chat_assistant": {"max_previous_conversation": 0},
        "enhancer_model": None,
        "assistant_model": None,
    }
    payload.update(overrides)
    return payload


@pytest.mark.asyncio
async def test_setting_lifecycle_journey(authed_client, db_session, mock_model_sync):
    await clear_setting_state(db_session)
    model = DfEngineModelOptionsFactory.create(type="text", is_available=True, is_enabled=True, is_main=True)

    # 1. nothing saved yet — GET returns defaults, no logs
    initial = await authed_client.call("GET", SETTING_URL)
    assert initial.json()["data"]["enhancer_model"] is None

    logs_initial = await authed_client.call("GET", LOGS_URL)
    assert logs_initial.json()["data"]["totalData"] == 0

    # 2. first save — settings rows inserted; the client sends the UID, the
    #    setting is stored/returned as the model name; not logged (no prior state)
    first_save = await authed_client.call("POST", SETTING_URL, json=_base_payload(enhancer_model=model.uid))
    assert first_save.status_code == 200
    assert first_save.json()["data"]["enhancer_model"] == model.name

    logs_after_first = await authed_client.call("GET", LOGS_URL)
    assert logs_after_first.json()["data"]["totalData"] == 0

    # 3. no-op save — same values, no log
    await authed_client.call("POST", SETTING_URL, json=_base_payload(enhancer_model=model.uid))
    logs_after_noop = await authed_client.call("GET", LOGS_URL)
    assert logs_after_noop.json()["data"]["totalData"] == 0

    # 4. real change — rate limit updated, one log records the diff (names, not UIDs)
    await authed_client.call(
        "POST",
        SETTING_URL,
        json=_base_payload(enhancer_model=model.uid, limit={"generate_per_min": 5, "enhance_per_min": 5}),
    )
    logs_after_change = await authed_client.call("GET", LOGS_URL)
    assert logs_after_change.json()["data"]["totalData"] == 1
    newest = logs_after_change.json()["data"]["paginated"][0]
    assert newest["incoming_data"]["limit"] == {"generate_per_min": 5, "enhance_per_min": 5}
    assert newest["previous_data"]["limit"] == {"generate_per_min": 0, "enhance_per_min": 0}
    assert newest["incoming_data"]["enhancer_model"] == model.name

    # 5. sync drops the model from OpenRouter — it's a main model still referenced
    #    by the enhancer setting, so sync flags it unavailable AND nulls the setting.
    rows = await available_model_rows(db_session, "text")
    mock_model_sync.set(
        "/models?output_modalities=text",
        [openrouter_item_from_row(r) for r in rows if r.model_id != model.model_id],
    )
    sync_resp = await authed_client.call("POST", MODELS_URL)
    assert sync_resp.status_code == 200

    after_sync = await authed_client.call("GET", SETTING_URL)
    assert after_sync.json()["data"]["enhancer_model"] is None

    # 6. the sync cascade is an audited change — a second log entry now exists
    logs_after_sync = await authed_client.call("GET", LOGS_URL)
    assert logs_after_sync.json()["data"]["totalData"] == 2

    # 7. the now-unavailable model can no longer be picked again
    rejected = await authed_client.call(
        "POST", SETTING_URL, json=_base_payload(enhancer_model=model.uid), raise_for_status=False
    )
    assert rejected.status_code == 422
