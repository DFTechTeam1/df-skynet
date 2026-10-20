import pytest
from sqlalchemy import select
from services.mysql.factory.df_engine_generations import DfEngineGenerationsFactory
from services.mysql.factory.df_engine_generation_results import DfEngineGenerationResultsFactory
from services.mysql.model.df_engine_model_options import DfEngineModelOptions
from services.mysql.model.df_engine_menus import DfEngineMenus
from services.mysql.model.df_engine_features import DfEngineFeatures

GALLERIES_URL = "/api/user-galleries"
FILES_URL = "/api/files"


def _uids(body):
    return {e["file_uid"] for e in body["data"]}


@pytest.mark.asyncio
async def test_set_main_moves_the_listed_entry_from_root_to_child(authed_client, project_task, user_id, db_session):
    """Walks a root+child family through favorite -> set-main, checking the /user-galleries
    response after each real API call. The list has one entry per generation - its current
    is_main result, keyed by file_uid - so favoriting a non-main child doesn't add it (this list
    isn't filtered on favourited_at), and only set-main flips which file_uid is listed."""
    model_option = (await db_session.execute(select(DfEngineModelOptions).limit(1))).scalars().first()
    menu = (await db_session.execute(select(DfEngineMenus).limit(1))).scalars().first()
    feature = (await db_session.execute(select(DfEngineFeatures).limit(1))).scalars().first()
    assert model_option and menu and feature, (
        "staging DB is missing model_options/menus/features rows to fixture against"
    )
    fks = {"model_id": model_option.id, "menu_id": menu.id, "feature_id": feature.id}

    root_generation = DfEngineGenerationsFactory.create(
        project_id=project_task.project_id, task_id=project_task.id, created_by=int(user_id), sourceable_id=1, **fks
    )
    root_result = DfEngineGenerationResultsFactory.create(
        generation_id=root_generation.id, created_by=int(user_id), is_main=True
    )
    child_generation = DfEngineGenerationsFactory.create(
        project_id=project_task.project_id, task_id=project_task.id, created_by=int(user_id), sourceable_id=1, **fks
    )
    child_result = DfEngineGenerationResultsFactory.create(
        generation_id=child_generation.id, created_by=int(user_id), is_main=False, parent_id=root_result.id
    )

    # 1. root is main and listed by its own file_uid; the child has no top-level entry of its own
    galleries = await authed_client.call("GET", f"{GALLERIES_URL}/{project_task.uid}")
    uids = _uids(galleries.json())
    assert str(root_result.uid) in uids
    assert str(child_result.uid) not in uids

    # 2. favorite the child via the real files API - favourited_at isn't filtered by this list,
    # so it stays absent regardless
    favorite_resp = await authed_client.call("POST", f"{FILES_URL}/favorite/{child_result.uid}", json={})
    assert favorite_resp.status_code == 200
    galleries = await authed_client.call("GET", f"{GALLERIES_URL}/{project_task.uid}")
    uids = _uids(galleries.json())
    assert str(root_result.uid) in uids
    assert str(child_result.uid) not in uids

    # 3. set the child as main via the real files API: is_main flips to the child, so the listed
    # file_uid flips too (cache invalidated by the write)
    set_main_resp = await authed_client.call("PATCH", f"{FILES_URL}/set-main/{child_result.uid}")
    assert set_main_resp.status_code == 200

    galleries = await authed_client.call("GET", f"{GALLERIES_URL}/{project_task.uid}")
    uids = _uids(galleries.json())
    assert str(child_result.uid) in uids
    assert str(root_result.uid) not in uids


@pytest.mark.asyncio
async def test_set_main_promoting_a_child_leaves_sibling_absorbed_not_floating(
    authed_client, project_task, user_id, db_session
):
    """A family is root + its direct children - exactly one member holds `is_main=True` at a time.
    Promoting one child to main must demote the root, and a sibling that was never main must stay
    absorbed (no independent top-level entry of its own), not be accidentally detached."""
    model_option = (await db_session.execute(select(DfEngineModelOptions).limit(1))).scalars().first()
    menu = (await db_session.execute(select(DfEngineMenus).limit(1))).scalars().first()
    feature = (await db_session.execute(select(DfEngineFeatures).limit(1))).scalars().first()
    assert model_option and menu and feature, (
        "staging DB is missing model_options/menus/features rows to fixture against"
    )
    fks = {"model_id": model_option.id, "menu_id": menu.id, "feature_id": feature.id}

    def _make(is_main, parent_id=None):
        generation = DfEngineGenerationsFactory.create(
            project_id=project_task.project_id,
            task_id=project_task.id,
            created_by=int(user_id),
            sourceable_id=1,
            **fks,
        )
        result = DfEngineGenerationResultsFactory.create(
            generation_id=generation.id, created_by=int(user_id), is_main=is_main, parent_id=parent_id
        )
        return generation, result

    root_generation, root_result = _make(is_main=True)
    promoted_generation, promoted_result = _make(is_main=False, parent_id=root_result.id)
    sibling_generation, _sibling_result = _make(is_main=False, parent_id=root_result.id)

    set_main_resp = await authed_client.call("PATCH", f"{FILES_URL}/set-main/{promoted_result.uid}")
    assert set_main_resp.status_code == 200

    galleries = await authed_client.call("GET", f"{GALLERIES_URL}/{project_task.uid}")
    uids = _uids(galleries.json())

    assert str(promoted_result.uid) in uids, "promoted result must appear at the top level, not be absorbed"
    assert str(root_result.uid) not in uids
    assert str(_sibling_result.uid) not in uids
