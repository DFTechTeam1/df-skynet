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
from services.redis import CacheKeys, client as redis_client, delete_pattern

URL = "/api/generations"

# Hardcoded in apps/controller/generations.py as `pic_id = 3  # Rudhi as example` —
# the only PIC the endpoint currently looks up an API key for.
PIC_EMPLOYEE_ID = 3


def _url(task_uid):
    return f"{URL}/{task_uid}"


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
    """An enabled/available video model — `get_model`'s supported_parameters filter
    only applies to image/image_edit, and `validate_model_params` skips video entirely."""
    return DfEngineModelOptionsFactory.create(
        type=ModelUsageTypes.video, is_enabled=True, is_available=True, deleted_at=None
    )


@pytest_asyncio.fixture
async def pic_api_key(db_session, user_id):
    """A main, non-expired API key for the hardcoded PIC employee (id 3). Any
    pre-existing key(s) on that employee are snapshotted and restored, matching
    the save/restore idiom `active_employee_uid` already uses for the same reason:
    this touches a real employee row on the shared staging DB."""
    preexisting = (
        (await db_session.execute(select(DfEngineApiKeys).where(DfEngineApiKeys.employee_id == PIC_EMPLOYEE_ID)))
        .scalars()
        .all()
    )
    preexisting_data = [row.model_dump() for row in preexisting]
    await db_session.execute(delete(DfEngineApiKeys).where(DfEngineApiKeys.employee_id == PIC_EMPLOYEE_ID))
    await db_session.commit()

    key = DfEngineApiKeysFactory.create(employee_id=PIC_EMPLOYEE_ID, is_main=True, created_by=int(user_id))
    try:
        yield key
    finally:
        await db_session.execute(delete(DfEngineApiKeys).where(DfEngineApiKeys.employee_id == PIC_EMPLOYEE_ID))
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
        type=ModelUsageTypes.text, is_enabled=True, is_available=True, deleted_at=None
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
        if previous_value is not None:
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
    """Fakes the two external side effects the create endpoint triggers: OpenRouter
    prompt ranking and the Celery image-generation dispatch. Returns the list of
    `.delay(...)` calls the fake task recorded."""

    async def _fake_rank_prompt(*args, **kwargs):
        return None

    delay_calls = []

    class _FakeImageGenerationTask:
        def delay(self, *args, **kwargs):
            delay_calls.append((args, kwargs))

    monkeypatch.setattr("apps.controller.generations.rank_prompt", _fake_rank_prompt)
    monkeypatch.setattr("apps.controller.generations.image_generation", _FakeImageGenerationTask())
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


@pytest.mark.asyncio
async def test_video_type_returns_early_with_no_data(
    authed_client,
    project_task,
    generation_menu_feature,
    video_model,
    pic_api_key,
    ranking_model,
    generation_project_settings,
    fake_generation_backends,
):
    """200 OK; `type="video"` hits the `match`'s catch-all arm and returns immediately
    with no data and no task dispatch — video generation isn't implemented yet."""
    menu, feature = generation_menu_feature
    resp = await authed_client.call(
        "POST", _url(project_task.uid), json=_payload(menu, feature, video_model, type="video")
    )
    assert resp.status_code == 200
    assert resp.json()["data"] is None
    assert len(fake_generation_backends) == 0


@pytest.mark.asyncio
async def test_unknown_menu_is_404(authed_client, project_task, generation_menu_feature, image_model):
    """404 menu_not_found when menu_uid matches no active menu — exercises `except BaseError: raise`."""
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
