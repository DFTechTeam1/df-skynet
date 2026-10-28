import pytest
import pytest_asyncio
from middlewares.lang import resolve_message
from uuid import uuid4
from sqlalchemy import delete, select
from services.mysql.factory.df_engine_api_keys import DfEngineApiKeysFactory
from services.mysql.factory.df_engine_menus import DfEngineMenusFactory
from services.mysql.factory.df_engine_features import DfEngineFeaturesFactory
from services.mysql.factory.df_engine_menu_feature_mappings import DfEngineMenuFeatureMappingsFactory
from services.mysql.factory.df_engine_model_options import DfEngineModelOptionsFactory
from services.mysql.model import DfEngineGenerations
from services.mysql.model.df_engine_api_keys import DfEngineApiKeys
from services.mysql.model.df_engine_model_options import ModelUsageTypes
from services.mysql.model.df_engine_project_settings import DfEngineProjectSettings
from services.mysql.model.employees import Employees
from services.mysql.model.entertainment_task_songs import (
    EntertainmentTaskSongs,
    SONG_STATUS_ACTIVE,
    SONG_STATUS_COMPLETED,
)
from services.mysql.model.project_person_in_charges import ProjectPersonInCharges
from services.mysql.model.project_song_lists import ProjectSongLists

URL = "/api/generations"


@pytest_asyncio.fixture
async def pic_employee_id(db_session, user_id) -> int:
    employee = (await db_session.execute(select(Employees).where(Employees.user_id == int(user_id)))).scalars().first()
    assert employee is not None and employee.boss_id is not None, "staging employee/boss_id missing for user_id"
    return employee.boss_id


@pytest_asyncio.fixture
async def pic_membership(db_session, project_task, pic_employee_id):
    """Registers the boss employee as a PIC on the fixture task's real project."""
    project_id = project_task.project_id
    existing = (
        (
            await db_session.execute(
                select(ProjectPersonInCharges).where(
                    ProjectPersonInCharges.project_id == project_id,
                    ProjectPersonInCharges.pic_id == pic_employee_id,
                )
            )
        )
        .scalars()
        .first()
    )
    # No branching on shared-DB state: `rows` is empty when the boss is already a PIC, so the same lines run
    # either way (and teardown only ever deletes a row this fixture created).
    rows = [] if existing else [ProjectPersonInCharges(project_id=project_id, pic_id=pic_employee_id, is_lead=False)]
    db_session.add_all(rows)
    await db_session.commit()
    try:
        yield
    finally:
        await db_session.execute(
            delete(ProjectPersonInCharges).where(ProjectPersonInCharges.id.in_([row.id for row in rows]))  # type: ignore
        )
        await db_session.commit()


@pytest_asyncio.fixture
async def pic_api_key(db_session, user_id, pic_employee_id, pic_membership):
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
        for data in preexisting_data:  # pragma: no cover - only hit if this employee already had a key
            db_session.add(DfEngineApiKeys(**data))
        await db_session.commit()


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
        supported_parameters={"input_references": {"max": 0}},
    )


@pytest_asyncio.fixture
async def ranking_model(db_session):
    import json
    from services.mysql.model.df_engine_settings import DfEngineSettings
    from services.redis import CacheKeys, client as redis_client, delete_pattern

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

    delay_calls = []

    class _FakeGenerationTask:
        def delay(self, *args, **kwargs):
            delay_calls.append((args, kwargs))

    monkeypatch.setattr("apps.controller.generations.validate_prompt", _fake_rank_prompt)
    monkeypatch.setattr("apps.controller.generations.image_generation", _FakeGenerationTask())
    monkeypatch.setattr("apps.controller.generations.video_generation", _FakeGenerationTask())
    return delay_calls


@pytest_asyncio.fixture
async def make_song(db_session, project_task, user_id):
    """Factory for a `project_song_lists` + `entertainment_task_songs` pair on the same
    real project as `project_task`, so the generation-project-settings/PIC fixtures
    (which key off `project_task.project_id`) still apply unchanged."""
    employee = (await db_session.execute(select(Employees).where(Employees.user_id == int(user_id)))).scalars().first()
    created: list[tuple[ProjectSongLists, EntertainmentTaskSongs]] = []

    async def _make(status: int) -> ProjectSongLists:
        song = ProjectSongLists(
            uid=str(uuid4()),
            project_id=project_task.project_id,
            name="Test Song",
            is_request_edit=False,
            is_request_delete=False,
            created_by=int(user_id),
        )
        db_session.add(song)
        await db_session.flush()

        assignment = EntertainmentTaskSongs(
            project_song_list_id=song.id,
            status=status,
            employee_id=employee.id,
            project_id=project_task.project_id,
        )
        db_session.add(assignment)
        await db_session.commit()
        created.append((song, assignment))
        return song

    try:
        yield _make
    finally:
        for song, assignment in created:
            await db_session.execute(delete(EntertainmentTaskSongs).where(EntertainmentTaskSongs.id == assignment.id))
            # A generation created against this song during the test still FK-references
            # it via song_id — drop those first so the song row itself can be deleted.
            await db_session.execute(delete(DfEngineGenerations).where(DfEngineGenerations.song_id == song.id))
            await db_session.execute(delete(ProjectSongLists).where(ProjectSongLists.id == song.id))
        await db_session.commit()


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
async def test_generating_against_a_song_task_sets_song_id_not_task_id(
    authed_client,
    make_song,
    generation_menu_feature,
    image_model,
    pic_api_key,
    ranking_model,
    generation_project_settings,
    fake_generation_backends,
    db_session,
):
    song = await make_song(SONG_STATUS_ACTIVE)
    menu, feature = generation_menu_feature
    resp = await authed_client.call("POST", f"{URL}/{song.uid}", json=_payload(menu, feature, image_model))
    assert resp.status_code == 200
    assert len(fake_generation_backends) == 1

    generation_uid = resp.json()["data"]["generation_uid"]
    row = (
        (await db_session.execute(select(DfEngineGenerations).where(DfEngineGenerations.uid == generation_uid)))
        .scalars()
        .first()
    )
    assert row.song_id == song.id
    assert row.task_id is None


@pytest.mark.asyncio
async def test_generating_against_a_completed_song_task_is_refused(
    authed_client,
    make_song,
    generation_menu_feature,
    image_model,
    pic_api_key,
    ranking_model,
    generation_project_settings,
    fake_generation_backends,
):
    """422 song_task_already_completed; a completed song can no longer be generated against."""
    song = await make_song(SONG_STATUS_COMPLETED)
    menu, feature = generation_menu_feature
    resp = await authed_client.call(
        "POST", f"{URL}/{song.uid}", json=_payload(menu, feature, image_model), raise_for_status=False
    )
    assert resp.status_code == 422
    assert resp.json()["message"] == resolve_message("song_task_already_completed", "en")
    assert fake_generation_backends == []
