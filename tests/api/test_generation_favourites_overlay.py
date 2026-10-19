import pytest
import pytest_asyncio
from services.dto import ConnectionContext
from services.dto.asynced.generation_files import (
    get_favourited_files,
    get_generation_files,
    get_generation_main_file_detail,
    get_generation_main_variants,
    overlay_favourites,
)
from services.mysql.factory.df_engine_generations import DfEngineGenerationsFactory
from services.mysql.factory.df_engine_generation_favourites import DfEngineGenerationFavouritesFactory
from services.mysql.factory.df_engine_generation_results import DfEngineGenerationResultsFactory
from services.mysql.factory.df_engine_model_options import DfEngineModelOptionsFactory
from services.mysql.factory.df_engine_menus import DfEngineMenusFactory
from services.mysql.factory.df_engine_features import DfEngineFeaturesFactory
from services.redis import CacheKeys, client as redis_client

URL = "/api/references-picker"


@pytest_asyncio.fixture
async def generation_fks(user_id) -> dict:
    model_option = DfEngineModelOptionsFactory.create()
    menu = DfEngineMenusFactory.create(created_by=int(user_id), df_engine_menu_feature_mapping=None)
    feature = DfEngineFeaturesFactory.create(created_by=int(user_id), df_engine_feature_prompt_mapping=None)
    return {"model_id": model_option.id, "menu_id": menu.id, "feature_id": feature.id}


@pytest.fixture
def ctx(db_session):
    return ConnectionContext(db_session, redis_client(), CacheKeys())


def _make_result(project_task, owner_id, generation_fks, **overrides):
    generation = DfEngineGenerationsFactory.create(
        project_id=project_task.project_id,
        task_id=project_task.id,
        created_by=int(owner_id),
        sourceable_id=1,
        **generation_fks,
    )
    return DfEngineGenerationResultsFactory.create(generation_id=generation.id, created_by=int(owner_id), **overrides)


@pytest.mark.asyncio
async def test_overlay_without_viewer_or_files_is_a_noop(ctx):
    """No viewer, or records with no file_uid (pending), come back untouched and run no query."""
    records = [{"file_uid": None, "action": {}}]
    assert await overlay_favourites(ctx, records, None) is records
    assert await overlay_favourites(ctx, records, 1) == [{"file_uid": None, "action": {}}]


@pytest.mark.asyncio
async def test_overlay_stamps_viewer_favourite_on_cached_records_and_nested_variants(
    ctx, project_task, user_id, other_user_id, generation_fks
):
    """A viewer-neutral cached record gets this viewer's favourited_at + flags (also on nested variants and an
    action-less record); someone else's favourite doesn't count."""
    fav = _make_result(project_task, user_id, generation_fks)
    other_fav = _make_result(project_task, user_id, generation_fks)
    DfEngineGenerationFavouritesFactory.create(user_id=int(user_id), result_id=fav.id)
    DfEngineGenerationFavouritesFactory.create(user_id=int(other_user_id), result_id=other_fav.id)
    plain = lambda: {"can_set_favorite": True}  # noqa: E731
    records = [
        {"file_uid": fav.uid, "action": plain(), "variants": [{"file_uid": other_fav.uid, "action": plain()}]},
        {"file_uid": other_fav.uid},
    ]

    await ctx.db.commit()  # end the session's snapshot so it sees the factory-committed rows
    out = await overlay_favourites(ctx, records, int(user_id))
    assert out[0]["favourited_at"] is not None and out[0]["action"] == {"can_set_favorite": False}
    assert (
        out[0]["variants"][0]["favourited_at"] is None and out[0]["variants"][0]["action"]["can_set_favorite"] is True
    )
    assert out[1]["favourited_at"] is None


@pytest.mark.asyncio
async def test_overlay_accepts_a_single_record(ctx, project_task, user_id, generation_fks):
    """A detail dict (not a list) is overlaid in place."""
    fav = _make_result(project_task, user_id, generation_fks)
    DfEngineGenerationFavouritesFactory.create(user_id=int(user_id), result_id=fav.id)
    detail = {"file_uid": fav.uid, "action": {"can_set_favorite": True}}
    await ctx.db.commit()
    assert (await overlay_favourites(ctx, detail, int(user_id)))["favourited_at"] is not None


@pytest.mark.asyncio
async def test_favourited_files_filters_and_cache(ctx, project_task, user_id, generation_fks):
    """project_id / task_id / song_id are optional filters; a repeat call is served from the per-filter cache."""
    result = _make_result(project_task, user_id, generation_fks)
    DfEngineGenerationFavouritesFactory.create(user_id=int(user_id), result_id=result.id)
    uid = str(result.uid)
    await ctx.db.commit()

    def uids(files):
        return [f["file_uid"] for f in files]

    assert uid in uids(await get_favourited_files(ctx, int(user_id)))
    assert uid in uids(await get_favourited_files(ctx, int(user_id), project_id=project_task.project_id))
    assert uid in uids(await get_favourited_files(ctx, int(user_id), task_id=project_task.id))
    assert uid not in uids(await get_favourited_files(ctx, int(user_id), project_id=-1))
    assert uid not in uids(await get_favourited_files(ctx, int(user_id), song_id=-1))
    assert uid in uids(await get_favourited_files(ctx, int(user_id), task_id=project_task.id))  # cache hit


@pytest.mark.asyncio
async def test_cached_lists_are_overlaid_per_viewer(ctx, project_task, user_id, other_user_id, generation_fks):
    """Second (cached) reads of the file list, detail and variants still reflect the current viewer's favourite."""
    result = _make_result(project_task, user_id, generation_fks, is_main=True)
    scope = dict(task_id=project_task.id)
    await ctx.db.commit()

    await get_generation_files(ctx, int(user_id), **scope)  # warm
    await get_generation_main_file_detail(ctx, result.uid, int(user_id))
    await get_generation_main_variants(ctx, result.uid, int(user_id))
    DfEngineGenerationFavouritesFactory.create(user_id=int(user_id), result_id=result.id)
    await ctx.db.commit()

    listed = await get_generation_files(ctx, int(user_id), **scope)
    assert next(f for f in listed if f["file_uid"] == str(result.uid))["favourited_at"] is not None
    assert (await get_generation_main_file_detail(ctx, result.uid, int(user_id)))["favourited_at"] is not None
    assert (await get_generation_main_variants(ctx, result.uid, int(user_id)))[0]["favourited_at"] is not None


@pytest.mark.asyncio
async def test_references_picker_flags_my_favourite_only(
    authed_client, project_task, user_id, other_user_id, generation_fks
):
    """200 OK; the picker's per-file favourited_at reflects the viewer's own favourite, on first and cached reads."""
    mine = _make_result(project_task, user_id, generation_fks)
    theirs = _make_result(project_task, user_id, generation_fks)
    DfEngineGenerationFavouritesFactory.create(user_id=int(user_id), result_id=mine.id)
    DfEngineGenerationFavouritesFactory.create(user_id=int(other_user_id), result_id=theirs.id)

    for _ in range(2):  # db, then cache
        resp = await authed_client.call("GET", f"{URL}/{project_task.project.uid}")
        files = next(s for s in resp.json()["data"] if s["type"] == "Image Generations")["files"]
        by_uid = {f["file_uid"]: f for f in files}
        assert by_uid[mine.uid]["favourited_at"] is not None
        assert by_uid[theirs.uid]["favourited_at"] is None
