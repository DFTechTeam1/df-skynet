import pytest
import pytest_asyncio
from uuid import uuid4
from middlewares.lang import resolve_message
from services.mysql.factory.df_engine_upload_files import DfEngineUploadFilesFactory
from services.mysql.factory.df_engine_generations import DfEngineGenerationsFactory
from services.mysql.factory.df_engine_generation_results import DfEngineGenerationResultsFactory
from services.mysql.factory.df_engine_model_options import DfEngineModelOptionsFactory
from services.mysql.factory.df_engine_menus import DfEngineMenusFactory
from services.mysql.factory.df_engine_features import DfEngineFeaturesFactory


def _url(file_uid):
    return f"/api/files/download/{file_uid}"


@pytest_asyncio.fixture
async def generation_fks(user_id) -> dict:
    """Self-contained model_option/menu/feature ids for df_engine_generations' NOT NULL FKs —
    created via factories rather than assumed to pre-exist, so this works on a fresh, empty DB too."""
    model_option = DfEngineModelOptionsFactory.create()
    menu = DfEngineMenusFactory.create(created_by=int(user_id), df_engine_menu_feature_mapping=None)
    feature = DfEngineFeaturesFactory.create(created_by=int(user_id), df_engine_feature_prompt_mapping=None)
    return {"model_id": model_option.id, "menu_id": menu.id, "feature_id": feature.id}


def _make_result(project_task, user_id, generation_fks, name="a.png", path="renders/render.mp4"):
    generation = DfEngineGenerationsFactory.create(
        project_id=project_task.project_id,
        task_id=project_task.id,
        created_by=int(user_id),
        sourceable_id=1,
        **generation_fks,
    )
    return DfEngineGenerationResultsFactory.create(
        name=name, path=path, generation_id=generation.id, created_by=int(user_id)
    )


@pytest.mark.asyncio
async def test_download_generated_file_success(authed_client, project_task, user_id, generation_fks, mock_udin):
    """200 OK; streams the generation result's raw bytes back with an attachment Content-Disposition.
    The stream is keyed off the result's storage `path` (what's actually requested upstream),
    not its `name` (only used for the Content-Disposition header)."""
    result = _make_result(project_task, user_id, generation_fks, name="render.mp4", path="renders/render.mp4")
    mock_udin.set_stream("renders/render.mp4", 200, b"fake-generated-bytes")

    resp = await authed_client.call("GET", _url(result.uid))
    assert resp.status_code == 200
    assert resp.content == b"fake-generated-bytes"
    assert "attachment" in resp.headers["content-disposition"]
    assert "render.mp4" in resp.headers["content-disposition"]


@pytest.mark.asyncio
async def test_download_unknown_uid_is_404(authed_client, project_task, mock_udin):
    """404 file_not_found; uid matches no generation result at all."""
    resp = await authed_client.call("GET", _url(uuid4()), raise_for_status=False)
    assert resp.status_code == 404
    assert resp.json()["message"] == resolve_message("file_not_found", "en")


@pytest.mark.asyncio
async def test_download_someone_elses_file_is_allowed(
    authed_client, project_task, other_user_id, generation_fks, mock_udin, as_roles
):
    """200 OK; any signed-in user, override role or not, can download a file another user generated."""
    as_roles(["staff"])
    result = _make_result(project_task, other_user_id, generation_fks, name="theirs.mp4", path="renders/theirs.mp4")
    mock_udin.set_stream("renders/theirs.mp4", 200, b"their-bytes")

    resp = await authed_client.call("GET", _url(result.uid))
    assert resp.status_code == 200
    assert resp.content == b"their-bytes"
    assert "theirs.mp4" in resp.headers["content-disposition"]


@pytest.mark.asyncio
async def test_download_uploaded_file_with_source_upload(authed_client, project_task, user_id, mock_udin):
    """200 OK; `source=upload` resolves the uid in df_engine_upload_files and streams its path."""
    upload = DfEngineUploadFilesFactory.create(
        name="ref.png", path="uploads/ref.png", project_id=project_task.project_id, created_by=int(user_id)
    )
    mock_udin.set_stream("uploads/ref.png", 200, b"fake-upload-bytes")

    resp = await authed_client.call("GET", _url(upload.uid), params={"source": "upload"})
    assert resp.status_code == 200
    assert resp.content == b"fake-upload-bytes"
    assert "ref.png" in resp.headers["content-disposition"]


@pytest.mark.asyncio
async def test_download_upload_uid_without_source_is_404(authed_client, project_task, user_id, mock_udin):
    """404; the default source is `generated`, so an upload uid is not found there."""
    upload = DfEngineUploadFilesFactory.create(project_id=project_task.project_id, created_by=int(user_id))
    resp = await authed_client.call("GET", _url(upload.uid), raise_for_status=False)
    assert resp.status_code == 404
    assert resp.json()["message"] == resolve_message("file_not_found", "en")


@pytest.mark.asyncio
async def test_download_unknown_upload_uid_is_404(authed_client, mock_udin):
    resp = await authed_client.call("GET", _url(uuid4()), params={"source": "upload"}, raise_for_status=False)
    assert resp.status_code == 404
    assert resp.json()["message"] == resolve_message("file_not_found", "en")


@pytest.mark.asyncio
async def test_download_generated_uid_with_source_upload_is_404(
    authed_client, project_task, user_id, generation_fks, mock_udin
):
    """404; `source=upload` only looks in df_engine_upload_files, never in generation results."""
    result = _make_result(project_task, user_id, generation_fks)
    resp = await authed_client.call("GET", _url(result.uid), params={"source": "upload"}, raise_for_status=False)
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_download_someone_elses_upload_is_allowed(
    authed_client, project_task, other_user_id, mock_udin, as_roles
):
    """200 OK; any signed-in user can download an upload made by another user."""
    as_roles(["staff"])
    upload = DfEngineUploadFilesFactory.create(
        name="theirs.png", path="uploads/theirs.png", project_id=project_task.project_id, created_by=other_user_id
    )
    mock_udin.set_stream("uploads/theirs.png", 200, b"their-upload")

    resp = await authed_client.call("GET", _url(upload.uid), params={"source": "upload"})
    assert resp.status_code == 200
    assert resp.content == b"their-upload"


@pytest.mark.asyncio
async def test_download_upload_streams_the_full_udin_url_not_the_raw_path(
    authed_client, project_task, user_id, mock_udin
):
    """The upstream request must use the formatted udin URL (scheme + host), never the bare storage path."""
    upload = DfEngineUploadFilesFactory.create(
        name="ref.png", path="uploads/ref.png", project_id=project_task.project_id, created_by=int(user_id)
    )
    mock_udin.set_stream("uploads/ref.png", 200, b"x")
    await authed_client.call("GET", _url(upload.uid), params={"source": "upload"})
    assert mock_udin.calls[-1][1].startswith(("http://", "https://"))


@pytest.mark.asyncio
async def test_download_upstream_error_is_not_a_200(authed_client, project_task, user_id, mock_udin):
    """The upstream is checked before the response starts, so a udin failure surfaces as an error status."""
    upload = DfEngineUploadFilesFactory.create(
        name="gone.png", path="uploads/gone.png", project_id=project_task.project_id, created_by=int(user_id)
    )
    mock_udin.set_stream("uploads/gone.png", 404, b"")
    resp = await authed_client.call("GET", _url(upload.uid), params={"source": "upload"}, raise_for_status=False)
    assert resp.status_code >= 400
