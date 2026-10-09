import pytest
import pytest_asyncio
from uuid import uuid4
from middlewares.lang import resolve_message
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
