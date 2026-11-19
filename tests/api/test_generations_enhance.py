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
    """The endpoint only queues the Celery task; capture the `.delay` call instead of hitting the broker."""
    delay_calls = []

    class _FakeEnhanceTask:
        def delay(self, *args, **kwargs):
            delay_calls.append((args, kwargs))

    monkeypatch.setattr("apps.controller.generations.prompt_enhancement", _FakeEnhanceTask())
    return delay_calls


@pytest.mark.asyncio
async def test_enhance_queues_and_returns_the_generation_uid(
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
    """200; only the generation uid is returned, a queued `enhancer` row is stored and the task is dispatched."""
    menu, feature = generation_menu_feature
    resp = await authed_client.call("POST", f"{URL}/{project_task.uid}", json=_payload(menu, feature))
    assert resp.status_code == 200
    data = resp.json()["data"]
    row = (
        (await db_session.execute(select(DfEngineGenerations).where(DfEngineGenerations.uid == data["gid"])))
        .scalars()
        .first()
    )
    assert row.task_id == project_task.id and row.song_id is None
    assert row.status == "queued"
    assert len(fake_enhancer) == 1


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

    monkeypatch.setattr("apps.controller.generations.dispatch_generation", _boom)
    menu, feature = generation_menu_feature
    resp = await authed_client.call(
        "POST", f"{URL}/{project_task.uid}", json=_payload(menu, feature), raise_for_status=False
    )
    assert resp.status_code == 500


@pytest.mark.asyncio
async def test_enhance_unknown_reference_uid_is_not_found(
    authed_client,
    project_task,
    generation_menu_feature,
    pic_api_key,
    ranking_model,
    generation_project_settings,
    fake_generation_backends,
    fake_enhancer,
):
    """404 file_not_found when a tagged upload uid does not exist."""
    menu, feature = generation_menu_feature
    uid = "11111111-1111-4111-8111-111111111111"
    refs = [{"uid": uid, "source": "upload"}]
    resp = await authed_client.call(
        "POST",
        f"{URL}/{project_task.uid}",
        json=_payload(menu, feature, prompt=f"a bird {uid}", references=refs),
        raise_for_status=False,
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_enhance_rejects_reference_not_tagged_in_prompt(
    authed_client, project_task, generation_menu_feature, fake_enhancer
):
    """422 when a reference uid is not present in the prompt text."""
    menu, feature = generation_menu_feature
    refs = [{"uid": "11111111-1111-4111-8111-111111111111", "source": "upload"}]
    resp = await authed_client.call(
        "POST", f"{URL}/{project_task.uid}", json=_payload(menu, feature, references=refs), raise_for_status=False
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_enhance_result_not_ready_while_queued(
    authed_client,
    project_task,
    generation_menu_feature,
    pic_api_key,
    ranking_model,
    generation_project_settings,
    fake_generation_backends,
    fake_enhancer,
):
    """GET result is 200 with data null until the worker marks the row success."""
    menu, feature = generation_menu_feature
    resp = await authed_client.call("POST", f"{URL}/{project_task.uid}", json=_payload(menu, feature))
    gid = resp.json()["data"]["gid"]
    result = await authed_client.call("GET", f"/api/generation-enhance-results/{gid}", raise_for_status=False)
    assert result.status_code == 200
    assert result.json() == {"message": resolve_message("enhance_not_ready", "en"), "data": None}
