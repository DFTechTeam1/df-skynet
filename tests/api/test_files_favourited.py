import pytest
import pytest_asyncio
from services.mysql.factory.df_engine_generations import DfEngineGenerationsFactory
from services.mysql.factory.df_engine_generation_favourites import DfEngineGenerationFavouritesFactory
from services.mysql.factory.df_engine_generation_results import DfEngineGenerationResultsFactory
from services.mysql.factory.df_engine_model_options import DfEngineModelOptionsFactory
from services.mysql.factory.df_engine_menus import DfEngineMenusFactory
from services.mysql.factory.df_engine_features import DfEngineFeaturesFactory
from utils import local_time
from schemas.format.files import IconKind, UserGeneratedFile

URL = "/api/files/favorites"


@pytest_asyncio.fixture
async def generation_fks(user_id) -> dict:
    model_option = DfEngineModelOptionsFactory.create()
    menu = DfEngineMenusFactory.create(created_by=int(user_id), df_engine_menu_feature_mapping=None)
    feature = DfEngineFeaturesFactory.create(created_by=int(user_id), df_engine_feature_prompt_mapping=None)
    return {"model_id": model_option.id, "menu_id": menu.id, "feature_id": feature.id}


def _make_generation(project_task, owner_id, generation_fks, task_id=None, **overrides):
    return DfEngineGenerationsFactory.create(
        project_id=project_task.project_id,
        task_id=task_id or project_task.id,
        created_by=int(owner_id),
        sourceable_id=1,
        **generation_fks,
        **overrides,
    )


def _make_result(generation, owner_id, **overrides):
    return DfEngineGenerationResultsFactory.create(generation_id=generation.id, created_by=int(owner_id), **overrides)


def _find_flat(files, uid):
    return next((f for f in files if f["file_uid"] == str(uid)), None)


@pytest.mark.asyncio
async def test_only_my_favourites_are_returned(authed_client, project_task, user_id, other_user_id, generation_fks):
    """200 OK; own and other people's files I favourited are listed; unfavourited files and files only someone else
    favourited are not."""
    mine = _make_result(_make_generation(project_task, user_id, generation_fks), user_id)
    theirs = _make_result(_make_generation(project_task, other_user_id, generation_fks), other_user_id)
    not_fav = _make_result(_make_generation(project_task, user_id, generation_fks), user_id)
    only_other = _make_result(_make_generation(project_task, user_id, generation_fks), user_id)
    DfEngineGenerationFavouritesFactory.create(user_id=int(user_id), result_id=mine.id)
    DfEngineGenerationFavouritesFactory.create(user_id=int(user_id), result_id=theirs.id)
    DfEngineGenerationFavouritesFactory.create(user_id=int(other_user_id), result_id=only_other.id)

    resp = await authed_client.call("GET", URL, params={"task_id": project_task.id})
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert _find_flat(data, mine.uid) and _find_flat(data, theirs.uid)
    assert _find_flat(data, not_fav.uid) is None and _find_flat(data, only_other.uid) is None


@pytest.mark.asyncio
async def test_variants_are_listed_flat_newest_favourite_first(authed_client, project_task, user_id, generation_fks):
    """200 OK; a non-main variant is its own item, and items are ordered by favourited_at descending."""
    generation = _make_generation(project_task, user_id, generation_fks)
    root = _make_result(generation, user_id, is_main=True, version=1)
    variant = _make_result(generation, user_id, is_main=False, version=2, parent_id=root.id)
    DfEngineGenerationFavouritesFactory.create(
        user_id=int(user_id), result_id=root.id, favourited_at=local_time().replace(year=2020)
    )
    DfEngineGenerationFavouritesFactory.create(user_id=int(user_id), result_id=variant.id)

    data = (await authed_client.call("GET", URL, params={"task_id": project_task.id})).json()["data"]
    uids = [f["file_uid"] for f in data]
    assert uids.index(str(variant.uid)) < uids.index(str(root.uid))


@pytest.mark.asyncio
async def test_entry_is_a_user_generated_file(authed_client, project_task, user_id, other_user_id, generation_fks):
    """200 OK; each entry is a `UserGeneratedFile` without variants/references, plus the project name; actions are
    per-file ownership (no archive on someone else's file)."""
    mine = _make_result(_make_generation(project_task, user_id, generation_fks), user_id)
    theirs = _make_result(_make_generation(project_task, other_user_id, generation_fks), other_user_id)
    for r in (mine, theirs):
        DfEngineGenerationFavouritesFactory.create(user_id=int(user_id), result_id=r.id)

    data = (await authed_client.call("GET", URL, params={"task_id": project_task.id})).json()["data"]
    file = _find_flat(data, mine.uid)
    assert file["favourited_at"] is not None
    assert file["generation_uid"] and file["id"] == mine.id
    assert file.keys() == (set(UserGeneratedFile.model_fields) | set(IconKind.model_fields)) - {
        "variants",
        "references",
    } | {"project"}
    assert file["project"]
    assert file["action"]["can_set_favorite"] is False
    assert _find_flat(data, theirs.uid)["action"]["can_rename"] is False


@pytest.mark.asyncio
async def test_favourites_search(authed_client, project_task, user_id, generation_fks):
    """200 OK; search matches file name, file path, project name and task name, else nothing."""
    result = _make_result(_make_generation(project_task, user_id, generation_fks), user_id)
    DfEngineGenerationFavouritesFactory.create(user_id=int(user_id), result_id=result.id)
    file = _find_flat((await authed_client.call("GET", URL)).json()["data"], result.uid)

    for term in (result.name, result.path, file["project"], file["task"]):
        found = (await authed_client.call("GET", URL, params={"search": term})).json()["data"]
        assert _find_flat(found, result.uid) is not None, term
    none = (await authed_client.call("GET", URL, params={"search": "no-such-term-\u2603"})).json()["data"]
    assert _find_flat(none, result.uid) is None


@pytest.mark.asyncio
async def test_no_filter_returns_every_favourite_and_project_filter_narrows(
    authed_client, project_task, user_id, generation_fks
):
    """200 OK; with no query params all of my favourites come back; project_id / song_id narrow the list."""
    result = _make_result(_make_generation(project_task, user_id, generation_fks), user_id)
    DfEngineGenerationFavouritesFactory.create(user_id=int(user_id), result_id=result.id)

    everything = (await authed_client.call("GET", URL)).json()["data"]
    in_project = (await authed_client.call("GET", URL, params={"project_id": project_task.project_id})).json()["data"]
    other_project = (await authed_client.call("GET", URL, params={"project_id": -1})).json()["data"]
    other_song = (await authed_client.call("GET", URL, params={"song_id": -1})).json()["data"]
    assert _find_flat(everything, result.uid) and _find_flat(in_project, result.uid)
    assert _find_flat(other_project, result.uid) is None and _find_flat(other_song, result.uid) is None


@pytest.mark.asyncio
async def test_scoped_to_task_id(authed_client, project_task, user_id, generation_fks, db_session):
    """200 OK; a favourite on a sibling task of the same project isn't returned for this task."""
    from sqlalchemy import select
    from services.mysql.model import ProjectTasks

    sibling_task = (
        (
            await db_session.execute(
                select(ProjectTasks).where(
                    ProjectTasks.project_id == project_task.project_id, ProjectTasks.id != project_task.id
                )
            )
        )
        .scalars()
        .first()
    )
    assert sibling_task is not None, "the fixture project needs a second task to prove the task scoping"
    here = _make_result(_make_generation(project_task, user_id, generation_fks), user_id)
    there = _make_result(_make_generation(project_task, user_id, generation_fks, task_id=sibling_task.id), user_id)
    for result in (here, there):
        DfEngineGenerationFavouritesFactory.create(user_id=int(user_id), result_id=result.id)

    data = (await authed_client.call("GET", URL, params={"task_id": project_task.id})).json()["data"]
    assert _find_flat(data, here.uid) and _find_flat(data, there.uid) is None
