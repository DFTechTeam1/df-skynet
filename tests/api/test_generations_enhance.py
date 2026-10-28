import pytest
from sqlalchemy import select
from middlewares.lang import resolve_message
from services.mysql.model import DfEngineGenerations
from tests.api.test_generations_song_tasks import (  # noqa: F401  (fixtures)
    fake_generation_backends,
    generation_menu_feature,
    generation_project_settings,
    pic_api_key,
    pic_employee_id,
    pic_membership,
    ranking_model,
)

URL = "/api/generations/enhance"


def _payload(menu, feature, **overrides):
    return {"prompt": "a scenic mountain", "menu_uid": str(menu.uid), "feature_uid": str(feature.uid), **overrides}


@pytest.fixture
def fake_enhancer(monkeypatch):
    async def _enhance(prompt, model_id, key, user_id):
        return {"text": "enhanced!", "status_code": 200, "usage": {"total_tokens": 3, "cost": 0.1}}

    monkeypatch.setattr("apps.controller.generations.enhance_prompt", _enhance)


@pytest.mark.asyncio
async def test_enhance_returns_and_records_the_enhanced_prompt(
    authed_client,
    project_task,
    generation_menu_feature,
    pic_api_key,
    ranking_model,
    generation_project_settings,
    fake_generation_backends,
    fake_enhancer,
    db_session,
):
    """200; the enhanced text is returned and an `enhancer` generation row is stored against the task."""
    menu, feature = generation_menu_feature
    resp = await authed_client.call("POST", f"{URL}/{project_task.uid}", json=_payload(menu, feature))
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["prompt"] == "enhanced!"
    row = (
        (await db_session.execute(select(DfEngineGenerations).where(DfEngineGenerations.uid == data["enhance_uid"])))
        .scalars()
        .first()
    )
    assert row.task_id == project_task.id and row.song_id is None


@pytest.mark.asyncio
async def test_enhance_rejects_a_prompt_over_the_project_limit(
    authed_client,
    project_task,
    generation_menu_feature,
    pic_api_key,
    ranking_model,
    generation_project_settings,
    monkeypatch,
):
    async def _settings(ctx, project_uid=None):
        return {"compose_input_max_chars": 3}

    monkeypatch.setattr("apps.controller.generations.get_project_setting", _settings)
    menu, feature = generation_menu_feature
    resp = await authed_client.call(
        "POST", f"{URL}/{project_task.uid}", json=_payload(menu, feature), raise_for_status=False
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_enhance_without_a_configured_enhancer_model_is_422(
    authed_client,
    project_task,
    generation_menu_feature,
    generation_project_settings,
    monkeypatch,
):
    async def _admin(ctx):
        return {}

    monkeypatch.setattr("apps.controller.generations.get_admin_settings", _admin)
    menu, feature = generation_menu_feature
    resp = await authed_client.call(
        "POST", f"{URL}/{project_task.uid}", json=_payload(menu, feature), raise_for_status=False
    )
    assert resp.status_code == 422
    assert resp.json()["message"] == resolve_message("enhancer_model_not_configured", "en")


@pytest.mark.asyncio
async def test_enhance_unexpected_failure_is_500(
    authed_client,
    project_task,
    generation_menu_feature,
    pic_api_key,
    ranking_model,
    generation_project_settings,
    fake_generation_backends,
    monkeypatch,
):
    async def _boom(*a, **k):
        raise RuntimeError("boom")

    monkeypatch.setattr("apps.controller.generations.enhance_prompt", _boom)
    menu, feature = generation_menu_feature
    resp = await authed_client.call(
        "POST", f"{URL}/{project_task.uid}", json=_payload(menu, feature), raise_for_status=False
    )
    assert resp.status_code == 500
