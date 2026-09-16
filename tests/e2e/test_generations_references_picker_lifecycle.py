import pytest
from sqlalchemy import select
from middlewares.lang import resolve_message
from services.mysql.factory.df_engine_generations import DfEngineGenerationsFactory
from services.mysql.factory.df_engine_generation_results import DfEngineGenerationResultsFactory
from services.mysql.model import DfEngineFeatures, DfEngineMenus, DfEngineModelOptions

PICKER_URL = "/api/references-picker"
FILES_URL = "/api/files"


@pytest.mark.asyncio
async def test_archive_rejected_then_favorite_moves_result_across_picker_sections(
    authed_client, project_task, user_id, db_session
):
    """Walks a generation result through a rejected archive attempt then a favorite, checking the
    references-picker response after each real API call. The picker only ever lists `is_main=True`
    results (Image/Video Generation), and `is_main=True` results can't be archived directly - so
    archiving a picker-visible result must 422, proving cache invalidation and filtering
    (live-only, favourites regardless of kind-section) still hold for the calls that do succeed."""
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

    # 1. freshly created main result: live, shows up in Image Generation
    picker = await authed_client.call("GET", f"{PICKER_URL}/{project_task.uid}")
    assert result.uid in [f["uid"] for f in _picker_section(picker.json(), "Image Generation")["files"]]

    # 2. archiving the current main is rejected via the real files API
    archive_resp = await authed_client.call(
        "PATCH",
        f"{FILES_URL}/{project_task.uid}/archieve",
        json={"file_uids": [str(result.uid)]},
        raise_for_status=False,
    )
    assert archive_resp.status_code == 422
    assert archive_resp.json()["error"] == {"file_uids.0": [resolve_message("file_already_archived", "en")]}

    # 3. still live and unaffected by the rejected call
    picker = await authed_client.call("GET", f"{PICKER_URL}/{project_task.uid}")
    assert result.uid in [f["uid"] for f in _picker_section(picker.json(), "Image Generation")["files"]]

    # 4. favorite it via the real files API - no is_main restriction on favouriting
    favorite_resp = await authed_client.call(
        "PATCH", f"{FILES_URL}/{project_task.uid}/favorite", json={"file_uids": [str(result.uid)]}
    )
    assert favorite_resp.status_code == 200

    # 5. live and favourited: appears in both its kind section and Favorites
    picker = await authed_client.call("GET", f"{PICKER_URL}/{project_task.uid}")
    body = picker.json()
    assert result.uid in [f["uid"] for f in _picker_section(body, "Image Generation")["files"]]
    assert result.uid in [f["uid"] for f in _picker_section(body, "Favorites")["files"]]
