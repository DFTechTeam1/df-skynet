import pytest
from sqlalchemy import select
from services.mysql.factory.df_engine_generations import DfEngineGenerationsFactory
from services.mysql.factory.df_engine_generation_results import DfEngineGenerationResultsFactory
from services.mysql.model.df_engine_model_options import DfEngineModelOptions
from services.mysql.model.df_engine_menus import DfEngineMenus
from services.mysql.model.df_engine_features import DfEngineFeatures

GALLERIES_URL = "/api/user-galleries"
FILES_URL = "/api/files"


def _entry(body, generation_uid):
    return next((e for e in body["data"]["paginated"] if e["generation_uid"] == str(generation_uid)), None)


@pytest.mark.asyncio
async def test_favorite_and_set_main_move_result_across_galleries(authed_client, project_task, user_id, db_session):
    """Walks a root+variant family through favorite -> set-main, checking the /user-galleries
    response after each real API call to prove cache invalidation and is_main flips hold end to end."""
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

    # 1. root is main and absorbs the child as a counted variant; child has no top-level entry
    galleries = await authed_client.call("GET", f"{GALLERIES_URL}/{project_task.uid}")
    root_entry = _entry(galleries.json(), root_generation.uid)
    assert root_entry["is_main"] is True
    assert root_entry["total_variant"] == 2
    assert _entry(galleries.json(), child_generation.uid) is None

    # 2. favorite the child via the real files API (cache invalidated by the write)
    favorite_resp = await authed_client.call(
        "PATCH", f"{FILES_URL}/{project_task.uid}/favorite", json={"file_uids": [str(child_result.uid)]}
    )
    assert favorite_resp.status_code == 200

    # 3. set the child as main via the real files API: is_main flips to the child. The old root's
    # own parent_id isn't reassigned to the new main, so the child's own family shrinks to itself.
    set_main_resp = await authed_client.call("PATCH", f"{FILES_URL}/{project_task.uid}/set-main/{child_result.uid}")
    assert set_main_resp.status_code == 200

    galleries = await authed_client.call("GET", f"{GALLERIES_URL}/{project_task.uid}")
    body = galleries.json()
    child_entry = _entry(body, child_generation.uid)
    assert child_entry["is_main"] is True
    assert child_entry["total_variant"] == 1
    assert _entry(body, root_generation.uid) is None


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

    set_main_resp = await authed_client.call("PATCH", f"{FILES_URL}/{project_task.uid}/set-main/{promoted_result.uid}")
    assert set_main_resp.status_code == 200

    galleries = await authed_client.call("GET", f"{GALLERIES_URL}/{project_task.uid}")
    body = galleries.json()

    promoted_entry = _entry(body, promoted_generation.uid)
    assert promoted_entry is not None, "promoted result must appear at the top level, not be absorbed"
    assert promoted_entry["is_main"] is True
    assert _entry(body, root_generation.uid) is None
    assert _entry(body, sibling_generation.uid) is None
