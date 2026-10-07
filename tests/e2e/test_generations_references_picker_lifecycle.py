import pytest
from sqlalchemy import select
from apps.secret import DB_ASYNC_URL
from services.mysql import make_session
from services.mysql.factory.df_engine_generations import DfEngineGenerationsFactory
from services.mysql.factory.df_engine_generation_results import DfEngineGenerationResultsFactory
from services.mysql.model import DfEngineFeatures, DfEngineGenerationResults, DfEngineMenus, DfEngineModelOptions


async def _fetch_result(uid: str) -> DfEngineGenerationResults:
    """A fresh connection/transaction, independent of the `db_session` fixture (which may already
    hold an older REPEATABLE READ snapshot from earlier fixture setup) - guarantees the current
    committed DB state."""
    async with make_session(DB_ASYNC_URL)() as session:
        return (
            await session.execute(select(DfEngineGenerationResults).where(DfEngineGenerationResults.uid == uid))
        ).scalar_one()


PICKER_URL = "/api/references-picker"
FILES_URL = "/api/files"


@pytest.mark.asyncio
async def test_archive_is_noop_for_main_result_then_favorite_does_not_bust_stale_picker_cache(
    authed_client, project_task, user_id, db_session
):
    """Walks a generation result through an archive attempt then a favorite, checking the
    references-picker response and the DB row after each real API call. Two current gaps, both
    documented here rather than silently patched: (1) the archive endpoint's own UPDATE only ever
    touches `is_main=False` rows, but its validation step doesn't mirror that restriction, so
    archiving an is_main result returns 200 and reports it as archived while the DB row is left
    untouched; (2) neither the archive nor the favorite endpoint invalidates the references-picker
    cache, so a picker response fetched before the mutation stays stale (missing the favorite)
    until its own TTL expires - proven here by the favorite's DB write actually landing while the
    already-cached picker response doesn't reflect it."""
    model_option = (await db_session.execute(select(DfEngineModelOptions).limit(1))).scalars().first()
    menu = (await db_session.execute(select(DfEngineMenus).limit(1))).scalars().first()
    feature = (await db_session.execute(select(DfEngineFeatures).limit(1))).scalars().first()
    assert model_option and menu and feature, (
        "staging DB is missing model_options/menus/features rows to fixture against"
    )

    generation = DfEngineGenerationsFactory.create(
        project_id=project_task.project_id,
        task_id=project_task.id,
        created_by=int(user_id),
        sourceable_id=1,
        model_id=model_option.id,
        menu_id=menu.id,
        feature_id=feature.id,
    )
    result = DfEngineGenerationResultsFactory.create(generation_id=generation.id, created_by=int(user_id), is_main=True)

    def _picker_section(body, type_name):
        return next(s for s in body["data"] if s["type"] == type_name)

    picker_url = f"{PICKER_URL}/{project_task.project.uid}"

    # 1. freshly created main result: live, shows up in Image Generations
    picker = await authed_client.call("GET", picker_url)
    assert result.uid in [f["file_uid"] for f in _picker_section(picker.json(), "Image Generations")["files"]]

    # 2. archiving the current main "succeeds" (200, reported as archived) via the real files API,
    # but the row is_main=True so the underlying UPDATE excludes it - a silent no-op
    archive_resp = await authed_client.call(
        "PATCH",
        f"{FILES_URL}/{project_task.uid}/archieve",
        json={"file_uids": [str(result.uid)]},
    )
    assert archive_resp.status_code == 200
    assert result.uid in [f["file_uid"] for f in archive_resp.json()["data"]]

    db_row = await _fetch_result(result.uid)
    assert db_row.archieved_at is None

    # 3. still live in the picker - the no-op archive never touched the row
    picker = await authed_client.call("GET", picker_url)
    assert result.uid in [f["file_uid"] for f in _picker_section(picker.json(), "Image Generations")["files"]]

    # 4. favorite it via the real files API - no is_main restriction, this write actually lands
    favorite_resp = await authed_client.call(
        "PATCH", f"{FILES_URL}/{project_task.uid}/favorite", json={"file_uids": [str(result.uid)]}
    )
    assert favorite_resp.status_code == 200
    assert result.uid in [f["file_uid"] for f in favorite_resp.json()["data"]]

    db_row = await _fetch_result(result.uid)
    assert db_row.favourited_at is not None

    # 5. the picker's cached response predates the favorite and neither mutation endpoint
    # invalidates it, so it still shows the pre-favorite state - a stale-cache gap, not correctness
    picker = await authed_client.call("GET", picker_url)
    body = picker.json()
    file = next(f for f in _picker_section(body, "Image Generations")["files"] if f["file_uid"] == result.uid)
    assert file["favourited_at"] is None
