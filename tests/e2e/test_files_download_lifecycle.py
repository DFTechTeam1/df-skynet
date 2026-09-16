import pytest
from uuid import uuid4
from middlewares.lang import resolve_message
from services.mysql.factory.df_engine_generations import DfEngineGenerationsFactory
from services.mysql.factory.df_engine_generation_results import DfEngineGenerationResultsFactory
from services.mysql.factory.df_engine_upload_files import DfEngineUploadFilesFactory
from services.mysql.factory.df_engine_model_options import DfEngineModelOptionsFactory
from services.mysql.factory.df_engine_menus import DfEngineMenusFactory
from services.mysql.factory.df_engine_features import DfEngineFeaturesFactory


def _url(task_uid, suffix=""):
    return f"/api/files/{task_uid}{suffix}"


def _find_file_node(nodes, uid):
    for node in nodes:
        found = next((f for f in node["files"] if f["uid"] == uid), None)
        if found is not None:
            return found
        found = _find_file_node(node["childs"], uid)
        if found is not None:
            return found
    return None


@pytest.fixture
def generation_fks(user_id) -> dict:
    model_option = DfEngineModelOptionsFactory.create()
    menu = DfEngineMenusFactory.create(created_by=int(user_id), df_engine_menu_feature_mapping=None)
    feature = DfEngineFeaturesFactory.create(created_by=int(user_id), df_engine_feature_prompt_mapping=None)
    return {"model_id": model_option.id, "menu_id": menu.id, "feature_id": feature.id}


@pytest.mark.asyncio
async def test_full_files_download_lifecycle(authed_client, project_task, user_id, generation_fks, mock_udin):
    """Walks upload -> tree shows can_download True -> download matches bytes, for both an
    uploaded file and a generation result, then confirms a bogus uid 404s under either source."""
    project_uid = project_task.project.uid

    upload_row = DfEngineUploadFilesFactory.create(
        path=f"storage/DF-Engine/{project_uid}/upload/images/original.png",
        name="original.png",
        project_id=project_task.project_id,
        task_id=project_task.id,
        created_by=int(user_id),
    )
    generation = DfEngineGenerationsFactory.create(
        project_id=project_task.project_id,
        task_id=project_task.id,
        created_by=int(user_id),
        sourceable_id=1,
        **generation_fks,
    )
    result_row = DfEngineGenerationResultsFactory.create(
        path=f"storage/DF-Engine/{project_uid}/generated/images/render.png",
        name="render.png",
        generation_id=generation.id,
        created_by=int(user_id),
    )

    # 1. the tree shows can_download True for the uploaded file
    listed = await authed_client.call("GET", _url(project_task.uid))
    node = _find_file_node(listed.json()["data"], upload_row.uid)
    assert node["action"]["can_download"] is True
    assert _find_file_node(listed.json()["data"], str(uuid4())) is None

    # 2. downloading it returns the exact bytes udin holds for that path
    mock_udin.set_stream("original.png", 200, b"original-bytes")
    upload_download = await authed_client.call("GET", _url(project_task.uid, f"/download/upload/{upload_row.uid}"))
    assert upload_download.status_code == 200
    assert upload_download.content == b"original-bytes"
    assert "original.png" in upload_download.headers["content-disposition"]

    # 3. same for the generation result, via source=generated
    mock_udin.set_stream("render.png", 200, b"render-bytes")
    generated_download = await authed_client.call(
        "GET", _url(project_task.uid, f"/download/generated/{result_row.uid}")
    )
    assert generated_download.status_code == 200
    assert generated_download.content == b"render-bytes"
    assert "render.png" in generated_download.headers["content-disposition"]

    # 4. a bogus uid 404s under either source
    for source in ("upload", "generated"):
        resp = await authed_client.call(
            "GET", _url(project_task.uid, f"/download/{source}/{uuid4()}"), raise_for_status=False
        )
        assert resp.status_code == 404
        assert resp.json()["message"] == resolve_message("file_not_found", "en")
