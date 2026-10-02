import json
import pytest
import pytest_asyncio
from types import SimpleNamespace
from sqlalchemy import delete, select
from middlewares.lang import resolve_message
from services.mysql.factory.df_engine_api_keys import DfEngineApiKeysFactory
from services.mysql.factory.df_engine_menus import DfEngineMenusFactory
from services.mysql.factory.df_engine_features import DfEngineFeaturesFactory
from services.mysql.factory.df_engine_menu_feature_mappings import DfEngineMenuFeatureMappingsFactory
from services.mysql.factory.df_engine_model_options import DfEngineModelOptionsFactory
from services.mysql.model.df_engine_api_keys import DfEngineApiKeys
from services.mysql.model.df_engine_model_options import ModelUsageTypes
from services.mysql.model.df_engine_project_settings import DfEngineProjectSettings
from services.mysql.model.df_engine_settings import DfEngineSettings
from services.mysql.model.employees import Employees
from services.redis import CacheKeys, client as redis_client, delete_pattern

URL = "/api/generations"


def _url(task_uid):
    return f"{URL}/{task_uid}"


@pytest_asyncio.fixture
async def pic_employee_id(db_session, user_id) -> int:
    """The authenticated user's boss — the endpoint looks up its API key via
    `employee_boss["id"]`, resolved from the real staging `employees` row."""
    employee = (await db_session.execute(select(Employees).where(Employees.user_id == int(user_id)))).scalars().first()
    assert employee is not None and employee.boss_id is not None, "staging employee/boss_id missing for user_id"
    return employee.boss_id


@pytest_asyncio.fixture
async def generation_menu_feature(user_id):
    """A menu with exactly one feature mapped under it, satisfying `validate_features`."""
    menu = DfEngineMenusFactory.create(created_by=int(user_id), df_engine_menu_feature_mapping=None)
    feature = DfEngineFeaturesFactory.create(created_by=int(user_id), df_engine_feature_prompt_mapping=None)
    DfEngineMenuFeatureMappingsFactory.create(df_engine_menus=menu, df_engine_features=feature)
    return menu, feature


@pytest_asyncio.fixture
async def image_model():
    """An enabled/available image model with a minimal `supported_parameters` shape
    (only `input_references`, popped before the required-keys check) so an empty
    `parameter: {}` payload passes `validate_model_image` untouched."""
    return DfEngineModelOptionsFactory.create(
        type=ModelUsageTypes.image,
        is_enabled=True,
        is_available=True,
        deleted_at=None,
        supported_parameters={"input_references": {"max": 0}},
    )


@pytest_asyncio.fixture
async def video_model():
    """An enabled/available video model with the non-empty `supported_*` JSON arrays
    `get_model`'s video-specific filters require (`json_length(...) >= 1` on each of
    supported_resolutions/aspect_ratios/sizes/durations/frame_images)."""
    return DfEngineModelOptionsFactory.create(
        type=ModelUsageTypes.video,
        is_enabled=True,
        is_available=True,
        deleted_at=None,
        supported_resolutions=["720p"],
        supported_aspect_ratios=["16:9"],
        supported_sizes=["1280x720"],
        supported_durations=[5],
        supported_frame_images=["first_frame"],
    )


@pytest_asyncio.fixture
async def pic_api_key(db_session, user_id, pic_employee_id):
    """A main, non-expired API key for the authenticated user's boss employee. Any
    pre-existing key(s) on that employee are snapshotted and restored, matching
    the save/restore idiom `active_employee_uid` already uses for the same reason:
    this touches a real employee row on the shared staging DB."""
    preexisting = (
        (await db_session.execute(select(DfEngineApiKeys).where(DfEngineApiKeys.employee_id == pic_employee_id)))
        .scalars()
        .all()
    )
    preexisting_data = [row.model_dump() for row in preexisting]
    await db_session.execute(delete(DfEngineApiKeys).where(DfEngineApiKeys.employee_id == pic_employee_id))
    await db_session.commit()

    key = DfEngineApiKeysFactory.create(employee_id=pic_employee_id, is_main=True, created_by=int(user_id))
    try:
        yield key
    finally:
        await db_session.execute(delete(DfEngineApiKeys).where(DfEngineApiKeys.employee_id == pic_employee_id))
        for data in preexisting_data:  # pragma: no cover - only hit if this employee already had a key on the shared DB
            db_session.add(DfEngineApiKeys(**data))
        await db_session.commit()


@pytest_asyncio.fixture
async def ranking_model(db_session):
    """Configures a real, enabled/available text model as the admin `enhancer_model`,
    satisfying `rank_prompt`'s required-ranking-model guard in the generations
    controller. Writes the `DfEngineSettings` row directly (not via `POST /setting`,
    which full-replaces `folder_depth_limit`/`admin_view` too and would clobber
    shared state) and snapshots/restores it, matching this file's other fixtures."""
    model = DfEngineModelOptionsFactory.create(
        type=ModelUsageTypes.text,
        is_enabled=True,
        is_available=True,
        deleted_at=None,
        default_parameters={"temperature": 0.7},
    )
    existing = (
        (
            await db_session.execute(
                select(DfEngineSettings).where(
                    DfEngineSettings.code == "admin_setting", DfEngineSettings.key == "enhancer_model"
                )
            )
        )
        .scalars()
        .first()
    )
    previous_value = existing.value if existing else None
    await db_session.execute(
        delete(DfEngineSettings).where(
            DfEngineSettings.code == "admin_setting", DfEngineSettings.key == "enhancer_model"
        )
    )
    db_session.add(
        DfEngineSettings(
            code="admin_setting", key="enhancer_model", value=json.dumps({"uid": model.uid, "name": model.name})
        )
    )
    await db_session.commit()
    await delete_pattern(redis_client(), CacheKeys().setting_global())
    try:
        yield model
    finally:
        await db_session.execute(
            delete(DfEngineSettings).where(
                DfEngineSettings.code == "admin_setting", DfEngineSettings.key == "enhancer_model"
            )
        )
        if previous_value is not None:  # pragma: no cover - only hit if enhancer_model was already configured
            db_session.add(DfEngineSettings(code="admin_setting", key="enhancer_model", value=previous_value))
        await db_session.commit()
        await delete_pattern(redis_client(), CacheKeys().setting_global())


@pytest_asyncio.fixture
async def generation_project_settings(db_session, project_task):
    """A generous `df_engine_project_settings` row for the fixture task's real
    project, so `validate_prompt_length`/`validate_api_key_limitation` take the
    project_setting branch instead of the global project-class-limits fallback.
    Any pre-existing row for this project is snapshotted and restored."""
    project_id = project_task.project_id
    preexisting = (
        (
            await db_session.execute(
                select(DfEngineProjectSettings).where(DfEngineProjectSettings.project_id == project_id)
            )
        )
        .scalars()
        .all()
    )
    preexisting_data = [row.model_dump() for row in preexisting]
    if preexisting_data:  # pragma: no cover - only hit if this project already had a row on the shared DB
        await db_session.execute(
            delete(DfEngineProjectSettings).where(DfEngineProjectSettings.project_id == project_id)
        )
        await db_session.commit()

    db_session.add(
        DfEngineProjectSettings(
            project_id=project_id,
            token_usage_limit=1_000_000,
            compose_input_max_chars=100_000,
            storyboard_prompt_chars=1000,
            max_scene_per_storyboard=10,
            max_shot_per_scene=10,
            token_limit_threshold=1.0,
        )
    )
    await db_session.commit()
    try:
        yield
    finally:
        await db_session.execute(
            delete(DfEngineProjectSettings).where(DfEngineProjectSettings.project_id == project_id)
        )
        for data in preexisting_data:  # pragma: no cover - only hit if this project already had a row on the shared DB
            db_session.add(DfEngineProjectSettings(**data))
        await db_session.commit()


@pytest_asyncio.fixture
def fake_generation_backends(monkeypatch):
    """Fakes the external side effects the create endpoint triggers: OpenRouter
    prompt ranking and the Celery image/video-generation dispatch. Returns the list
    of `.delay(...)` calls either fake task recorded."""

    async def _fake_rank_prompt(*args, **kwargs):
        return None

    delay_calls = []

    class _FakeGenerationTask:
        def delay(self, *args, **kwargs):
            delay_calls.append((args, kwargs))

    monkeypatch.setattr("apps.controller.generations.rank_prompt", _fake_rank_prompt)
    monkeypatch.setattr("apps.controller.generations.image_generation", _FakeGenerationTask())
    monkeypatch.setattr("apps.controller.generations.video_generation", _FakeGenerationTask())
    return delay_calls


def _payload(menu, feature, model, **overrides):
    return {
        "prompt": "a scenic mountain view at sunrise",
        "model_uid": str(model.uid),
        "menu_uid": str(menu.uid),
        "feature_uid": str(feature.uid),
        "references": [],
        "type": "image",
        "parameter": {},
        **overrides,
    }


@pytest.mark.asyncio
async def test_image_generation_happy_path_dispatches_task_and_returns_galleries(
    authed_client,
    project_task,
    generation_menu_feature,
    image_model,
    pic_api_key,
    ranking_model,
    generation_project_settings,
    fake_generation_backends,
):
    """200 OK; a valid image request creates the generation, dispatches the fake
    Celery task exactly once, and returns only the newly created record as a
    single object (the FE is expected to refetch the user-galleries endpoint
    for the full list)."""
    menu, feature = generation_menu_feature
    resp = await authed_client.call("POST", _url(project_task.uid), json=_payload(menu, feature, image_model))
    assert resp.status_code == 200
    assert len(fake_generation_backends) == 1

    body = resp.json()["data"]
    assert isinstance(body, dict)
    assert body["type"] == "image"
    assert body["is_main"] is None
    assert "variants" not in body


@pytest.mark.asyncio
async def test_response_is_the_new_generation_not_a_prior_one(
    authed_client,
    project_task,
    generation_menu_feature,
    image_model,
    pic_api_key,
    ranking_model,
    generation_project_settings,
    fake_generation_backends,
):
    """200 OK; a second generation on the same task returns only itself — an earlier
    generation on that task must not be reflected in the response."""
    menu, feature = generation_menu_feature
    first = await authed_client.call("POST", _url(project_task.uid), json=_payload(menu, feature, image_model))
    first_uid = first.json()["data"]["generation_uid"]

    second = await authed_client.call("POST", _url(project_task.uid), json=_payload(menu, feature, image_model))
    assert second.json()["data"]["generation_uid"] != first_uid


def _video_payload(menu, feature, model, **overrides):
    return _payload(
        menu,
        feature,
        model,
        type="video",
        parameter={"resolution": "720p", "aspect_ratio": "16:9", "duration": 5},
        **overrides,
    )


@pytest.mark.asyncio
async def test_video_generation_happy_path_dispatches_task_and_returns_galleries(
    authed_client,
    project_task,
    generation_menu_feature,
    video_model,
    pic_api_key,
    ranking_model,
    generation_project_settings,
    fake_generation_backends,
):
    """200 OK; a valid video request creates the generation, dispatches the fake
    Celery video task exactly once, and returns the newly created record."""
    menu, feature = generation_menu_feature
    resp = await authed_client.call("POST", _url(project_task.uid), json=_video_payload(menu, feature, video_model))
    assert resp.status_code == 200
    assert len(fake_generation_backends) == 1

    body = resp.json()["data"]
    assert isinstance(body, dict)
    assert body["type"] == "video"
    assert body["is_main"] is None
    assert "variants" not in body


@pytest.mark.asyncio
async def test_video_generation_invalid_parameter_is_422(
    authed_client,
    project_task,
    generation_menu_feature,
    video_model,
    pic_api_key,
    ranking_model,
    generation_project_settings,
    fake_generation_backends,
):
    """422 generation_parameters_invalid; a video request missing required
    parameters (resolution/aspect_ratio/duration) never reaches task dispatch."""
    menu, feature = generation_menu_feature
    payload = _payload(menu, feature, video_model, type="video")
    resp = await authed_client.call("POST", _url(project_task.uid), json=payload, raise_for_status=False)
    assert resp.status_code == 422
    assert resp.json()["message"] == resolve_message("generation_parameters_invalid", "en")
    assert len(fake_generation_backends) == 0


@pytest.mark.asyncio
async def test_unknown_menu_is_404(
    authed_client, project_task, generation_menu_feature, image_model, generation_project_settings
):
    """404 menu_not_found when menu_uid matches no active menu — exercises `except BaseError: raise`.
    Needs `generation_project_settings` since `get_project_setting` runs before the menu lookup and
    would otherwise 422 on this project having no project_class_limitations configured."""
    _menu, feature = generation_menu_feature
    unmapped_menu = SimpleNamespace(uid="00000000-0000-0000-0000-000000000000")
    payload = _payload(unmapped_menu, feature, image_model)
    resp = await authed_client.call("POST", _url(project_task.uid), json=payload, raise_for_status=False)
    assert resp.status_code == 404
    assert resp.json()["message"] == resolve_message("menu_not_found", "en")


@pytest.mark.asyncio
async def test_requires_auth(client, project_task):
    """401 when the request carries no bearer token."""
    resp = await client.call(
        "POST", _url(project_task.uid), json={"prompt": "x", "parameter": {}}, raise_for_status=False
    )
    assert resp.status_code == 401
