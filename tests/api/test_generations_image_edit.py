import pytest
import pytest_asyncio
from sqlalchemy import delete, select
from middlewares.lang import resolve_message
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

URL = "/api/generations/image-edit"

# Hardcoded in apps/controller/generations.py as `pic_id = 3  # Rudhi as example`.
PIC_EMPLOYEE_ID = 3

# Same exclude set the endpoint's `GenerationResultRecord(...).model_dump(exclude=...)` uses,
# so the response must always have exactly the complement of these keys.
EXCLUDED_KEYS = {"flag_created_at", "flag_favourited_at", "flag_archieved_at", "version", "updated_at", "parameter"}


def _url(file_uid):
    return f"{URL}/{file_uid}"


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
    import json

    db_session.add(
        DfEngineSettings(
            code="admin_setting", key="enhancer_model", value=json.dumps({"uid": model.uid, "name": model.name})
        )
    )
    await db_session.commit()
    from services.redis import CacheKeys, client as redis_client, delete_pattern

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


@pytest_asyncio.fixture
async def source_root(project_task, user_id, image_model, generation_menu_feature):
    """A pre-existing, standalone (root, no parent) generated image owned by the
    authenticated user - the file `POST /generations/image-edit/{file_uid}` targets."""
    menu, feature = generation_menu_feature
    generation = DfEngineGenerationsFactory.create(
        project_id=project_task.project_id,
        task_id=project_task.id,
        created_by=int(user_id),
        sourceable_id=1,
        model_id=image_model.id,
        menu_id=menu.id,
        feature_id=feature.id,
    )
    return DfEngineGenerationResultsFactory.create(generation_id=generation.id, created_by=int(user_id), is_main=True)


@pytest_asyncio.fixture
async def source_child(source_root, project_task, user_id, image_model, generation_menu_feature):
    """A non-root version (version 2, parented to `source_root`) of the same family."""
    menu, feature = generation_menu_feature
    generation = DfEngineGenerationsFactory.create(
        project_id=project_task.project_id,
        task_id=project_task.id,
        created_by=int(user_id),
        sourceable_id=1,
        model_id=image_model.id,
        menu_id=menu.id,
        feature_id=feature.id,
    )
    return DfEngineGenerationResultsFactory.create(
        generation_id=generation.id, created_by=int(user_id), is_main=False, parent_id=source_root.id, version=2
    )


def _payload(menu, feature, model, **overrides):
    return {
        "prompt": "make the sky more dramatic",
        "model_uid": str(model.uid),
        "menu_uid": str(menu.uid),
        "feature_uid": str(feature.uid),
        "references": [],
        "parameter": {},
        **overrides,
    }


@pytest.mark.asyncio
async def test_editing_a_root_file_sets_parent_id_to_its_own_id(
    authed_client,
    source_root,
    generation_menu_feature,
    image_model,
    pic_api_key,
    ranking_model,
    generation_project_settings,
    fake_generation_backends,
):
    """200 OK; editing a root (no parent) file chains the new generation onto that
    root's own id, and dispatches the fake Celery task exactly once."""
    menu, feature = generation_menu_feature
    resp = await authed_client.call("POST", _url(source_root.uid), json=_payload(menu, feature, image_model))
    assert resp.status_code == 200
    assert len(fake_generation_backends) == 1

    body = resp.json()["data"]
    assert body["parent_id"] == source_root.id
    assert body["kind"] == "image_edit"


@pytest.mark.asyncio
async def test_editing_a_child_file_chains_to_its_root_not_itself(
    authed_client,
    source_child,
    source_root,
    generation_menu_feature,
    image_model,
    pic_api_key,
    ranking_model,
    generation_project_settings,
    fake_generation_backends,
):
    """200 OK; editing an already-non-root version still resolves `parent_id` to the
    family's root id, not to the edited version's own id - lineage stays one level deep."""
    menu, feature = generation_menu_feature
    resp = await authed_client.call("POST", _url(source_child.uid), json=_payload(menu, feature, image_model))
    assert resp.status_code == 200
    assert resp.json()["data"]["parent_id"] == source_root.id


@pytest.mark.asyncio
async def test_response_format_matches_the_plain_generate_endpoint(
    authed_client,
    source_root,
    generation_menu_feature,
    image_model,
    pic_api_key,
    ranking_model,
    generation_project_settings,
    fake_generation_backends,
):
    """200 OK; the edit endpoint's response carries exactly the same key set as
    `POST /generations/{task_uid}` (both build the same `GenerationResultRecord`
    with the same exclude set) - only `parent_id` is actually populated here."""
    menu, feature = generation_menu_feature
    resp = await authed_client.call("POST", _url(source_root.uid), json=_payload(menu, feature, image_model))
    body = resp.json()["data"]
    expected_keys = {
        "id",
        "kind",
        "file_uid",
        "generation_uid",
        "parent_id",
        "name",
        "is_main",
        "path",
        "size",
        "created_at",
        "favourited_at",
        "archieved_at",
        "icon",
        "color",
        "status",
        "creator",
        "cost_usd",
        "cost_idr",
        "model",
        "prompt",
        "full_prompt",
        "action",
        "type",
    }
    assert set(body.keys()) == expected_keys
    assert not (set(body.keys()) & EXCLUDED_KEYS)


@pytest.mark.asyncio
async def test_n_other_than_one_is_rejected(
    authed_client,
    source_root,
    generation_menu_feature,
    image_model,
    pic_api_key,
    ranking_model,
    generation_project_settings,
    fake_generation_backends,
):
    """422; image-edit generations must always produce exactly one result, so `n` != 1 is rejected."""
    menu, feature = generation_menu_feature
    resp = await authed_client.call(
        "POST",
        _url(source_root.uid),
        json=_payload(menu, feature, image_model, parameter={"n": 2}),
        raise_for_status=False,
    )
    assert resp.status_code == 422
    assert len(fake_generation_backends) == 0


@pytest.mark.asyncio
async def test_reference_count_matches_requested_file_not_all_its_siblings(
    authed_client,
    project_task,
    user_id,
    generation_menu_feature,
    image_model,
    pic_api_key,
    ranking_model,
    generation_project_settings,
    fake_generation_backends,
    db_session,
):
    """200 OK; editing one file whose generation produced 3 sibling results (n=3) must
    create exactly 1 `DfEngineGenerationReferences` row (the edited file itself),
    not 3 - regression test for the `get_generation_files` over-fetch bug."""
    from sqlalchemy import select
    from services.mysql.model import DfEngineGenerationReferences

    menu, feature = generation_menu_feature
    batch_generation = DfEngineGenerationsFactory.create(
        project_id=project_task.project_id,
        task_id=project_task.id,
        created_by=int(user_id),
        sourceable_id=1,
        model_id=image_model.id,
        menu_id=menu.id,
        feature_id=feature.id,
    )
    siblings = [
        DfEngineGenerationResultsFactory.create(
            generation_id=batch_generation.id, created_by=int(user_id), is_main=(i == 0)
        )
        for i in range(3)
    ]
    target = siblings[0]

    resp = await authed_client.call("POST", _url(target.uid), json=_payload(menu, feature, image_model))
    assert resp.status_code == 200

    new_generation_id = select(DfEngineGenerationReferences).where(
        DfEngineGenerationReferences.result_id.in_([s.id for s in siblings])
    )
    rows = (await db_session.execute(new_generation_id)).scalars().all()
    assert len(rows) == 1
    assert rows[0].result_id == target.id


@pytest.mark.asyncio
async def test_requires_auth(client, source_root):
    """401 when the request carries no bearer token."""
    resp = await client.call(
        "POST", _url(source_root.uid), json={"prompt": "x", "parameter": {}}, raise_for_status=False
    )
    assert resp.status_code == 401
