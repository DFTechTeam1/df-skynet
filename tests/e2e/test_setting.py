"""End-to-end journey for DF Engine admin settings: initial fetch, first save
(logged with null previous_data), a no-op save (not logged), a real change
(logged with the actual diff), and the enhancer-model validation + disable
cascade wired through model_management.
"""

import pytest
from typing import Any
from uuid import uuid4
from services.mysql.model import DfEngineModelOptions
from tests.helpers import create_record, clear_setting_state

SETTING_URL = "/api/setting"
LOGS_URL = "/api/setting/logs"
MODELS_URL = "/api/models"


def _model_option_data(**overrides: Any) -> dict[str, Any]:
    unique = uuid4().hex[:10]
    data = dict(
        uid=str(uuid4()),
        model_id=f"test-vendor/test-model-{unique}",
        name=f"SettingJourney-{unique}",
        type="text",
        is_available=True,
        is_enabled=True,
        is_main=False,
    )
    data.update(overrides)
    return data


def _base_payload(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "admin_view": {"see_all_asset": True},
        "limit": {"generate_per_min": 0, "enhance_per_min": 0},
        "spend_ceiling": {"daily_ceiling_global_user": 0, "daily_ceiling_per_user": 0},
        "storyboard": {"max_storyboard_char": 4000, "max_scene_per_storyboard": 100, "max_shot_per_scene": 100},
        "compose_input": {"max_prompt_char": 4000},
        "enhancer_model": None,
        "assistant_model": None,
    }
    payload.update(overrides)
    return payload


@pytest.mark.asyncio
async def test_setting_lifecycle_journey(authed_client, db_session):
    await clear_setting_state(db_session)
    model = await create_record(db_session, DfEngineModelOptions, _model_option_data())

    # 1. nothing saved yet — GET returns defaults, no logs
    initial = await authed_client.call("GET", SETTING_URL)
    assert initial.json()["data"]["enhancer_model"] is None

    logs_initial = await authed_client.call("GET", LOGS_URL)
    assert logs_initial.json()["data"]["totalData"] == 0

    # 2. first save — settings created, one log with a null previous_data
    first_save = await authed_client.call("POST", SETTING_URL, json=_base_payload(enhancer_model=model.uid))
    assert first_save.status_code == 200
    assert first_save.json()["data"]["enhancer_model"]["uid"] == model.uid

    logs_after_first = await authed_client.call("GET", LOGS_URL)
    assert logs_after_first.json()["data"]["totalData"] == 1
    first_entry = logs_after_first.json()["data"]["paginated"][0]
    assert first_entry["previous_data"] is None
    assert first_entry["incoming_data"]["enhancer_model"] == model.uid

    # 3. no-op save — same values, no new log
    await authed_client.call("POST", SETTING_URL, json=_base_payload(enhancer_model=model.uid))
    logs_after_noop = await authed_client.call("GET", LOGS_URL)
    assert logs_after_noop.json()["data"]["totalData"] == 1

    # 4. real change — rate limit updated, second log records the diff
    await authed_client.call(
        "POST",
        SETTING_URL,
        json=_base_payload(enhancer_model=model.uid, limit={"generate_per_min": 5, "enhance_per_min": 5}),
    )
    logs_after_change = await authed_client.call("GET", LOGS_URL)
    assert logs_after_change.json()["data"]["totalData"] == 2
    newest = logs_after_change.json()["data"]["paginated"][0]
    assert newest["incoming_data"]["limit"] == {"generate_per_min": 5, "enhance_per_min": 5}
    assert newest["previous_data"]["limit"] == {"generate_per_min": 0, "enhance_per_min": 0}

    # 5. disabling the model that's currently the enhancer cascades it to null
    disable_resp = await authed_client.call("PATCH", f"{MODELS_URL}/{model.uid}", json={"is_enabled": False})
    assert disable_resp.status_code == 200
    assert disable_resp.json()["data"]["is_enabled"] is False

    after_disable = await authed_client.call("GET", SETTING_URL)
    assert after_disable.json()["data"]["enhancer_model"] is None

    # 6. the disable cascade is a direct DB fix, not a settings save — no new log entry
    logs_after_disable = await authed_client.call("GET", LOGS_URL)
    assert logs_after_disable.json()["data"]["totalData"] == 2

    # 7. the now-disabled model can no longer be picked again
    rejected = await authed_client.call(
        "POST", SETTING_URL, json=_base_payload(enhancer_model=model.uid), raise_for_status=False
    )
    assert rejected.status_code == 422
