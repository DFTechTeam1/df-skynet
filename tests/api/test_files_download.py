import pytest
from uuid import uuid4
from middlewares.lang import resolve_message
from services.mysql.factory.df_engine_generations import DfEngineGenerationsFactory
from services.mysql.factory.df_engine_generation_results import DfEngineGenerationResultsFactory
from services.mysql.factory.df_engine_upload_files import DfEngineUploadFilesFactory
from services.mysql.factory.df_engine_model_options import DfEngineModelOptionsFactory
from services.mysql.factory.df_engine_menus import DfEngineMenusFactory
from services.mysql.factory.df_engine_features import DfEngineFeaturesFactory
from services.mysql.model.df_engine_upload_files import UploadFileTypes


def _url(task_uid, source, file_uid):
    return f"/api/files/{task_uid}/download/{source}/{file_uid}"


def _make_file(project_task, user_id, name="a.png", kind="images", type=UploadFileTypes.image):
    """A `DfEngineUploadFiles` row shaped so `FilesService.base_of`/`type_root_of`
    recognize it, unlike the factory's default Faker path."""
    path = f"storage/DF-Engine/{project_task.project.uid}/upload/{kind}/{name}"
    return DfEngineUploadFilesFactory.create(
        path=path,
        name=name,
        project_id=project_task.project_id,
        task_id=project_task.id,
        created_by=int(user_id),
        type=type,
    )


@pytest.fixture
def generation_fks(user_id) -> dict:
    model_option = DfEngineModelOptionsFactory.create()
    menu = DfEngineMenusFactory.create(created_by=int(user_id), df_engine_menu_feature_mapping=None)
    feature = DfEngineFeaturesFactory.create(created_by=int(user_id), df_engine_feature_prompt_mapping=None)
    return {"model_id": model_option.id, "menu_id": menu.id, "feature_id": feature.id}


def _make_result(project_task, user_id, generation_fks, name="a.png", kind="images"):
    """A `DfEngineGenerationResults` row (with its parent `DfEngineGenerations`) shaped
    so `FilesService.base_of`/`type_root_of` recognize it, mirroring the upload-file helper."""
    generation = DfEngineGenerationsFactory.create(
        project_id=project_task.project_id,
        task_id=project_task.id,
        created_by=int(user_id),
        sourceable_id=1,
        **generation_fks,
    )
    path = f"storage/DF-Engine/{project_task.project.uid}/generated/{kind}/{name}"
    return DfEngineGenerationResultsFactory.create(
        path=path,
        name=name,
        generation_id=generation.id,
        created_by=int(user_id),
    )


@pytest.mark.asyncio
async def test_download_upload_file_success(authed_client, project_task, user_id, mock_udin):
    """200 OK; streams the raw bytes back with an attachment Content-Disposition."""
    row = _make_file(project_task, user_id, name="report.png")
    mock_udin.set_stream("report.png", 200, b"fake-upload-bytes")

    resp = await authed_client.call("GET", _url(project_task.uid, "upload", row.uid))
    assert resp.status_code == 200
    assert resp.content == b"fake-upload-bytes"
    assert "attachment" in resp.headers["content-disposition"]
    assert "report.png" in resp.headers["content-disposition"]


@pytest.mark.asyncio
async def test_download_generated_file_success(authed_client, project_task, user_id, generation_fks, mock_udin):
    """200 OK; a generation result downloads the same way as an uploaded file."""
    result = _make_result(project_task, user_id, generation_fks, name="render.mp4")
    mock_udin.set_stream("render.mp4", 200, b"fake-generated-bytes")

    resp = await authed_client.call("GET", _url(project_task.uid, "generated", result.uid))
    assert resp.status_code == 200
    assert resp.content == b"fake-generated-bytes"
    assert "attachment" in resp.headers["content-disposition"]
    assert "render.mp4" in resp.headers["content-disposition"]


@pytest.mark.asyncio
async def test_download_unknown_uid_is_404(authed_client, project_task, mock_udin):
    """404 file_not_found; uid matches no row in either table."""
    resp = await authed_client.call("GET", _url(project_task.uid, "upload", uuid4()), raise_for_status=False)
    assert resp.status_code == 404
    assert resp.json()["message"] == resolve_message("file_not_found", "en")


@pytest.mark.asyncio
async def test_download_wrong_source_is_404(authed_client, project_task, user_id, mock_udin):
    """404 file_not_found; an upload file's uid requested with source=generated does not
    fall back to the upload table."""
    row = _make_file(project_task, user_id)
    resp = await authed_client.call("GET", _url(project_task.uid, "generated", row.uid), raise_for_status=False)
    assert resp.status_code == 404
    assert resp.json()["message"] == resolve_message("file_not_found", "en")


@pytest.mark.asyncio
async def test_download_folder_uid_is_404(authed_client, project_task, user_id, mock_udin):
    """404 file_not_found; a folder row is never downloadable."""
    folder = _make_file(project_task, user_id, name="empty_sub", type=UploadFileTypes.folder)
    resp = await authed_client.call("GET", _url(project_task.uid, "upload", folder.uid), raise_for_status=False)
    assert resp.status_code == 404
    assert resp.json()["message"] == resolve_message("file_not_found", "en")


@pytest.mark.asyncio
async def test_download_someone_elses_file_is_404(authed_client, project_task, other_user_id, mock_udin):
    """404 file_not_found; ownership is enforced at the query, same as every other files endpoint."""
    row = _make_file(project_task, other_user_id)
    resp = await authed_client.call("GET", _url(project_task.uid, "upload", row.uid), raise_for_status=False)
    assert resp.status_code == 404
    assert resp.json()["message"] == resolve_message("file_not_found", "en")
