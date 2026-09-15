import pytest
from sqlalchemy import select
from services.mysql.factory.df_engine_generations import DfEngineGenerationsFactory
from services.mysql.factory.df_engine_generation_results import DfEngineGenerationResultsFactory
from services.mysql.model import DfEngineFeatures, DfEngineMenus, DfEngineModelOptions

PICKER_URL = "/api/references-picker"
FILES_URL = "/api/files"


@pytest.mark.asyncio
async def test_archive_then_favorite_move_result_across_picker_sections(
    authed_client, project_task, user_id, db_session
):
    """Walks a generation result through archive -> unarchive -> favorite, checking the
    references-picker response after each real API call to prove cache invalidation and
    filtering (live-only, favourites regardless of kind-section) hold end to end."""
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
    result = DfEngineGenerationResultsFactory.create(generation_id=generation.id, created_by=int(user_id))

    def _picker_section(body, type_name):
        return next(s for s in body["data"] if s["type"] == type_name)

    # 1. freshly created: live, shows up in Image Generation
    picker = await authed_client.call("GET", f"{PICKER_URL}/{project_task.uid}")
    assert result.uid in [f["uid"] for f in _picker_section(picker.json(), "Image Generation")["files"]]

    # 2. archive it via the real files API
    archive_resp = await authed_client.call(
        "PATCH", f"{FILES_URL}/{project_task.uid}/archieve", json={"file_uids": [str(result.uid)]}
    )
    assert archive_resp.status_code == 200

    # 3. archived results drop out of the picker entirely (cache invalidated by the archive call)
    picker = await authed_client.call("GET", f"{PICKER_URL}/{project_task.uid}")
    assert result.uid not in [f["uid"] for f in _picker_section(picker.json(), "Image Generation")["files"]]

    # 4. unarchive it back to live
    unarchive_resp = await authed_client.call(
        "PATCH",
        f"{FILES_URL}/{project_task.uid}/archieve",
        json={"file_uids": [str(result.uid)], "is_archieved": False},
    )
    assert unarchive_resp.status_code == 200

    # 5. favorite it via the real files API
    favorite_resp = await authed_client.call(
        "PATCH", f"{FILES_URL}/{project_task.uid}/favorite", json={"file_uids": [str(result.uid)]}
    )
    assert favorite_resp.status_code == 200

    # 6. now live again and favourited: appears in both its kind section and Favorites
    picker = await authed_client.call("GET", f"{PICKER_URL}/{project_task.uid}")
    body = picker.json()
    assert result.uid in [f["uid"] for f in _picker_section(body, "Image Generation")["files"]]
    assert result.uid in [f["uid"] for f in _picker_section(body, "Favorites")["files"]]
