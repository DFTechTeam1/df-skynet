import json
import pytest
import pytest_asyncio
from sqlalchemy import delete, select
from services.mysql.factory.df_engine_api_keys import DfEngineApiKeysFactory
from services.mysql.factory.df_engine_generations import DfEngineGenerationsFactory
from services.mysql.factory.df_engine_generation_results import DfEngineGenerationResultsFactory
from services.mysql.factory.df_engine_menus import DfEngineMenusFactory
from services.mysql.factory.df_engine_features import DfEngineFeaturesFactory
from services.mysql.factory.df_engine_menu_feature_mappings import DfEngineMenuFeatureMappingsFactory
from services.mysql.factory.df_engine_model_options import DfEngineModelOptionsFactory
from services.mysql.model.df_engine_api_keys import DfEngineApiKeys
from services.mysql.model.df_engine_model_options import ModelUsageTypes
from services.mysql.model.df_engine_project_settings import DfEngineProjectSettings
from services.mysql.model.df_engine_settings import DfEngineSettings
from services.redis import CacheKeys, client as redis_client, delete_pattern

EDIT_URL = "/api/generations/image-edit"
EDIT_RESULTS_URL = "/api/generation-edit-results"
MAIN_RESULTS_URL = "/api/generation-main-results"
PIC_EMPLOYEE_ID = 3


@pytest_asyncio.fixture
async def generation_menu_feature(user_id):
    menu = DfEngineMenusFactory.create(created_by=int(user_id), df_engine_menu_feature_mapping=None)
    feature = DfEngineFeaturesFactory.create(created_by=int(user_id), df_engine_feature_prompt_mapping=None)
    DfEngineMenuFeatureMappingsFactory.create(df_engine_menus=menu, df_engine_features=feature)
    return menu, feature


@pytest_asyncio.fixture
async def image_model():
    return DfEngineModelOptionsFactory.create(
        type=ModelUsageTypes.image,
        is_enabled=True,
        is_available=True,
        deleted_at=None,
        supported_parameters={"input_references": {"max": 1}},
    )


@pytest_asyncio.fixture
async def pic_api_key(db_session, user_id):
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
        for data in preexisting_data:  # pragma: no cover - only hit if this employee already had a key
            db_session.add(DfEngineApiKeys(**data))
        await db_session.commit()


@pytest_asyncio.fixture
async def ranking_model(db_session):
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
    if preexisting_data:  # pragma: no cover - only hit if this project already had a row
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
        for data in preexisting_data:  # pragma: no cover - only hit if this project already had a row
            db_session.add(DfEngineProjectSettings(**data))
        await db_session.commit()


@pytest_asyncio.fixture
def fake_generation_backends(monkeypatch):
    async def _fake_rank_prompt(*args, **kwargs):
        return None

    async def _fake_validate_references(references, *args, **kwargs):
        return references

    delay_calls = []

    class _FakeImageGenerationTask:
        def delay(self, *args, **kwargs):
            delay_calls.append((args, kwargs))

    monkeypatch.setattr("apps.controller.generations.rank_prompt", _fake_rank_prompt)
    monkeypatch.setattr("apps.controller.generations.validate_references", _fake_validate_references)
    monkeypatch.setattr("apps.controller.generations.image_generation", _FakeImageGenerationTask())
    return delay_calls


@pytest.mark.asyncio
async def test_edit_trigger_leaves_source_untouched_until_upload_completes(
    authed_client,
    project_task,
    user_id,
    generation_menu_feature,
    image_model,
    pic_api_key,
    ranking_model,
    generation_project_settings,
    fake_generation_backends,
):
    """Full loop against real endpoints (Celery/OpenRouter faked): a root file is
    edited via `POST /generations/image-edit/{file_uid}`, whose immediate response
    must chain `parent_id` back to the source. Since the actual new
    `DfEngineGenerationResults` row is only written later by the (here, un-run)
    `udin_uploader` Celery task, both `/generation-edit-results` and
    `/generation-main-results` must still describe the untouched source
    immediately afterwards - the trigger does not mutate the source synchronously."""
    menu, feature = generation_menu_feature
    source_generation = DfEngineGenerationsFactory.create(
        project_id=project_task.project_id,
        task_id=project_task.id,
        created_by=int(user_id),
        sourceable_id=1,
        model_id=image_model.id,
        menu_id=menu.id,
        feature_id=feature.id,
    )
    source = DfEngineGenerationResultsFactory.create(
        generation_id=source_generation.id, created_by=int(user_id), is_main=True, version=1
    )

    edit_resp = await authed_client.call(
        "POST",
        f"{EDIT_URL}/{source.uid}",
        json={
            "prompt": "make it look like golden hour",
            "model_uid": str(image_model.uid),
            "menu_uid": str(menu.uid),
            "feature_uid": str(feature.uid),
            "references": [],
            "parameter": {},
        },
    )
    assert edit_resp.status_code == 200
    assert edit_resp.json()["data"]["parent_id"] == source.id
    assert len(fake_generation_backends) == 1

    edit_results_resp = await authed_client.call("GET", f"{EDIT_RESULTS_URL}/{source_generation.uid}")
    main_results_resp = await authed_client.call("GET", f"{MAIN_RESULTS_URL}/{source_generation.uid}")
    assert edit_results_resp.json()["data"]["file_uid"] == str(source.uid)
    assert edit_results_resp.json()["data"]["is_main"] is True
    assert edit_results_resp.json()["data"]["version"] == 1
    assert main_results_resp.json()["data"]["file_uid"] == str(source.uid)
