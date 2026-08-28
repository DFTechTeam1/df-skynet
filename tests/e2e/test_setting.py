"""End-to-end journey for DF Engine admin settings: initial fetch, first save
(inserted, not logged — nothing to diff against), a no-op save (not logged), a
real change (logged with the actual diff), and the enhancer-model validation +
disable cascade wired through model_management.
"""

import pytest
from typing import Any
from services.mysql.factory.df_engine_model_options import DfEngineModelOptionsFactory
from tests.helpers import clear_setting_state

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
async def test_setting_lifecycle_journey(authed_client, db_session):
    await clear_setting_state(db_session)
    model = DfEngineModelOptionsFactory.create(type="text", is_available=True, is_enabled=True, is_main=False)

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

    # 5. disabling the model that's currently the enhancer cascades it to null
    disable_resp = await authed_client.call("PATCH", f"{MODELS_URL}/{model.uid}", json={"is_enabled": False})
    assert disable_resp.status_code == 200
    assert disable_resp.json()["data"]["is_enabled"] is False

    after_disable = await authed_client.call("GET", SETTING_URL)
    assert after_disable.json()["data"]["enhancer_model"] is None

    # 6. the disable cascade is a direct DB fix, not a settings save — no new log entry
    logs_after_disable = await authed_client.call("GET", LOGS_URL)
    assert logs_after_disable.json()["data"]["totalData"] == 1

    # 7. the now-disabled model can no longer be picked again
    rejected = await authed_client.call(
        "POST", SETTING_URL, json=_base_payload(enhancer_model=model.uid), raise_for_status=False
    )
    assert rejected.status_code == 422
