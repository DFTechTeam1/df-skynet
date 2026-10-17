import pytest
import pytest_asyncio
from uuid import uuid4
from middlewares.lang import resolve_message
from services.mysql.factory.df_engine_generations import DfEngineGenerationsFactory
from services.mysql.factory.df_engine_generation_results import DfEngineGenerationResultsFactory
from services.mysql.factory.df_engine_model_options import DfEngineModelOptionsFactory
from services.mysql.factory.df_engine_menus import DfEngineMenusFactory
from services.mysql.factory.df_engine_features import DfEngineFeaturesFactory

URL = "/api/user-galleries/generated"


def _url(file_uid):
    return f"{URL}/{file_uid}"


@pytest_asyncio.fixture
async def generation_fks(user_id) -> dict:
    """Self-contained model_option/menu/feature ids for df_engine_generations' NOT NULL FKs."""
    model_option = DfEngineModelOptionsFactory.create()
    menu = DfEngineMenusFactory.create(created_by=int(user_id), df_engine_menu_feature_mapping=None)
    feature = DfEngineFeaturesFactory.create(created_by=int(user_id), df_engine_feature_prompt_mapping=None)
    return {"model_id": model_option.id, "menu_id": menu.id, "feature_id": feature.id}


def _make_generation(project_task, user_id, generation_fks, **overrides):
    return DfEngineGenerationsFactory.create(
        project_id=project_task.project_id,
        task_id=project_task.id,
        created_by=int(user_id),
        sourceable_id=1,
        **generation_fks,
        **overrides,
    )


def _make_result(generation, user_id, **overrides):
    return DfEngineGenerationResultsFactory.create(generation_id=generation.id, created_by=int(user_id), **overrides)


@pytest.mark.asyncio
async def test_root_file_with_no_siblings_has_one_variant_and_no_variants_key(
    authed_client, project_task, user_id, generation_fks
):
    """200 OK; a standalone root (version 1, no children) reports a single-entry `variants` list."""
    generation = _make_generation(project_task, user_id, generation_fks)
    result = _make_result(generation, user_id, is_main=True, version=1)

    resp = await authed_client.call("GET", _url(result.uid))
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["file_uid"] == str(result.uid)
    assert data["is_main"] is True
    assert data["version"] == 1
    assert len(data["variants"]) == 1
    assert data["variants"][0]["file_uid"] == str(result.uid)


@pytest.mark.asyncio
async def test_root_file_with_children_lists_variants_sorted_by_version(
    authed_client, project_task, user_id, generation_fks
):
    """200 OK; fetching the root (version 1) of a multi-result family includes a `variants` list sorted by version."""
    root_generation = _make_generation(project_task, user_id, generation_fks)
    root = _make_result(root_generation, user_id, is_main=True, version=1)

    child_generation = _make_generation(project_task, user_id, generation_fks)
    child = _make_result(child_generation, user_id, is_main=False, parent_id=root.id, version=2)

    resp = await authed_client.call("GET", _url(root.uid))
    data = resp.json()["data"]
    assert data["file_uid"] == str(root.uid)
    assert "variants" in data
    assert len(data["variants"]) == 2
    versions = [v["version"] for v in data["variants"]]
    assert versions == sorted(versions)
    variant_uids = [v["file_uid"] for v in data["variants"]]
    assert str(root.uid) in variant_uids
    assert str(child.uid) in variant_uids


@pytest.mark.asyncio
async def test_non_root_version_fetched_directly_has_no_variants_key(
    authed_client, project_task, user_id, generation_fks
):
    """200 OK; fetching a non-root version directly returns a flat entry — no `variants` key even though
    the family has multiple rows, since the endpoint only attaches `variants` for the root (version 1)."""
    root_generation = _make_generation(project_task, user_id, generation_fks)
    root = _make_result(root_generation, user_id, is_main=True, version=1)

    child_generation = _make_generation(project_task, user_id, generation_fks)
    child = _make_result(child_generation, user_id, is_main=False, parent_id=root.id, version=2)

    resp = await authed_client.call("GET", _url(child.uid))
    data = resp.json()["data"]
    assert data["file_uid"] == str(child.uid)
    assert data["version"] == 2
    assert "variants" not in data


@pytest.mark.asyncio
async def test_response_is_cached_on_second_call(authed_client, project_task, user_id, generation_fks):
    """200 OK; second call returns identical data (served from the generation_file_detail cache key)."""
    generation = _make_generation(project_task, user_id, generation_fks)
    result = _make_result(generation, user_id, is_main=True, version=1)

    first = await authed_client.call("GET", _url(result.uid))
    second = await authed_client.call("GET", _url(result.uid))
    assert first.json()["data"] == second.json()["data"]


@pytest.mark.asyncio
async def test_unknown_file_is_404(authed_client):
    """404 main_generation_file_not_found for a file uid that matches no row."""
    resp = await authed_client.call("GET", _url(uuid4()), raise_for_status=False)
    assert resp.status_code == 404
    assert resp.json()["message"] == resolve_message("main_generation_file_not_found", "en")


@pytest.mark.asyncio
async def test_file_owned_by_another_user_is_still_visible(
    authed_client, project_task, generation_fks, other_user_id, as_roles
):
    """200 OK; the gallery is task-shared, so a file created by another member on the same task is
    still fetchable — visibility is task-scoped, not owner-scoped. `is_owner`-gated actions (e.g.
    `can_set_main`, `can_use_as_edit`) are what actually restrict what the viewer can do with it."""
    as_roles(["staff"])
    generation = _make_generation(project_task, other_user_id, generation_fks)
    result = _make_result(generation, other_user_id, is_main=True, version=1)

    resp = await authed_client.call("GET", _url(result.uid))
    data = resp.json()["data"]
    assert data["file_uid"] == str(result.uid)
    assert data["creator"]["user_id"] == int(other_user_id)
    assert data["action"]["can_set_main"] is False
    assert data["action"]["can_use_as_edit"] is False
    assert data["action"]["can_rename"] is False


@pytest.mark.asyncio
async def test_override_role_can_manage_another_users_file(
    authed_client, project_task, generation_fks, other_user_id, as_roles
):
    """200 OK; an override role gets rename/move/edit on someone else's file (detail and variants), while
    set-main and archive follow `is_main`/archive state, favourite stays owner-only. The shared cache must not leak the widened actions to a plain viewer afterwards."""
    generation = _make_generation(project_task, other_user_id, generation_fks)
    result = _make_result(generation, other_user_id, is_main=True, version=1)

    as_roles(["director"])
    data = (await authed_client.call("GET", _url(result.uid))).json()["data"]
    for action in (data["action"], data["variants"][0]["action"]):
        assert (action["can_rename"], action["can_choose_to_move"], action["can_use_as_edit"]) == (True,) * 3
        assert action["can_set_main"] is False  # it is already the main version
        assert action["can_archieve"] is False  # main versions cannot be archived

    as_roles(["staff"])
    data = (await authed_client.call("GET", _url(result.uid))).json()["data"]
    assert data["action"]["can_rename"] is False and data["variants"][0]["action"]["can_use_as_edit"] is False


@pytest.mark.asyncio
async def test_sibling_owned_by_another_user_is_still_visible(
    authed_client, project_task, user_id, generation_fks, other_user_id
):
    """200 OK; a sibling version created by another member of the same family is listed among the
    variants of a file the requesting user owns."""
    root_generation = _make_generation(project_task, user_id, generation_fks)
    root = _make_result(root_generation, user_id, is_main=True, version=1)

    other_generation = _make_generation(project_task, other_user_id, generation_fks)
    other = _make_result(other_generation, other_user_id, is_main=False, parent_id=root.id, version=2)

    resp = await authed_client.call("GET", _url(root.uid))
    data = resp.json()["data"]
    variant_uids = [v["file_uid"] for v in data["variants"]]
    assert str(other.uid) in variant_uids

    resp = await authed_client.call("GET", _url(other.uid))
    data = resp.json()["data"]
    assert data["file_uid"] == str(other.uid)
    assert data["creator"]["user_id"] == int(other_user_id)


@pytest.mark.asyncio
async def test_requires_auth(client, project_task):
    """401 when the request carries no bearer token."""
    resp = await client.call("GET", _url(uuid4()), raise_for_status=False)
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_main_file_detail_hides_archived_variants_but_they_stay_fetchable(
    authed_client, project_task, user_id, generation_fks
):
    """200 OK; the main file's `variants` omit archived versions, an archived version is still fetched directly by its own uid."""
    from utils import local_time

    generation = _make_generation(project_task, user_id, generation_fks)
    root = _make_result(generation, user_id, is_main=False, version=1)
    archived = _make_result(generation, user_id, is_main=False, version=2, parent_id=root.id, archieved_at=local_time())
    main = _make_result(generation, user_id, is_main=True, version=3, parent_id=root.id)

    data = (await authed_client.call("GET", _url(main.uid))).json()["data"]
    assert [v["file_uid"] for v in data["variants"]] == [str(root.uid), str(main.uid)]

    direct = (await authed_client.call("GET", _url(archived.uid))).json()["data"]
    assert direct["file_uid"] == str(archived.uid) and "variants" not in direct


@pytest.mark.asyncio
async def test_override_role_archive_and_favourite_set_updated_by_and_show_in_overriders_lists(
    authed_client, project_task, user_id, generation_fks, other_user_id, as_roles, db_session
):
    """200 OK; an override user archives/favourites another user's non-main file: `updated_by` becomes the overrider and the file shows in the overrider's archived and favourited lists."""
    from sqlalchemy import select
    from services.mysql.model import DfEngineGenerationResults

    generation = _make_generation(project_task, other_user_id, generation_fks)
    root = _make_result(generation, other_user_id, is_main=True, version=1)
    other = _make_result(generation, other_user_id, is_main=False, version=2, parent_id=root.id)
    base = f"/api/files/{project_task.uid}"

    as_roles(["director"])
    for suffix, body, key in (
        ("archieve", {"file_uids": [str(other.uid)], "is_archieved": True}, "archieved"),
        ("favorite", {"file_uids": [str(other.uid)], "is_favorited": True}, "favourited"),
    ):
        resp = await authed_client.call("PATCH", f"{base}/{suffix}", json=body)
        assert str(other.uid) in [f["file_uid"] for f in resp.json()["data"]]
        listed = await authed_client.call("GET", f"{base}/{key}")
        assert str(other.uid) in [f["file_uid"] for f in listed.json()["data"]]

    await db_session.commit()
    row = (
        await db_session.execute(select(DfEngineGenerationResults).where(DfEngineGenerationResults.id == other.id))
    ).scalar_one()
    assert row.updated_by == int(user_id) and row.archieved_at and row.favourited_at


@pytest.mark.asyncio
async def test_file_lists_are_scoped_to_the_task_not_the_project(
    authed_client, project_task, user_id, generation_fks, db_session
):
    """200 OK; with a sibling task in the same project, the favourited, archived and tree lists only return the task in the URL."""
    from sqlalchemy import select
    from services.mysql.model import ProjectTasks
    from utils import local_time

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

    mine = _make_generation(project_task, user_id, generation_fks)
    my_fav = _make_result(mine, user_id, is_main=True, version=1, favourited_at=local_time())
    my_arch = _make_result(mine, user_id, is_main=False, version=2, parent_id=my_fav.id, archieved_at=local_time())
    sibling = DfEngineGenerationsFactory.create(
        project_id=project_task.project_id,
        task_id=sibling_task.id,
        created_by=int(user_id),
        sourceable_id=1,
        **generation_fks,
    )
    other_fav = _make_result(sibling, user_id, is_main=True, version=1, favourited_at=local_time())
    other_arch = _make_result(
        sibling, user_id, is_main=False, version=2, parent_id=other_fav.id, archieved_at=local_time()
    )

    base = f"/api/files/{project_task.uid}"
    fav = {f["file_uid"] for f in (await authed_client.call("GET", f"{base}/favourited")).json()["data"]}
    arch = {f["file_uid"] for f in (await authed_client.call("GET", f"{base}/archieved")).json()["data"]}
    assert str(my_fav.uid) in fav and str(my_arch.uid) in arch
    assert str(other_fav.uid) not in fav and str(other_arch.uid) not in arch

    # the tree is project-wide; `task_uid` narrows it to this task, so the sibling task's files stay out
    tree = (
        await authed_client.call(
            "GET", f"/api/files/{project_task.project.uid}", params={"task_uid": str(project_task.uid)}
        )
    ).json()["data"]
    tree_uids, stack = set(), [tree]
    while stack:
        node = stack.pop()
        tree_uids.update(f["file_uid"] for f in node.get("files") or [])
        stack.extend(node.get("children") or [])
    assert str(other_fav.uid) not in tree_uids
