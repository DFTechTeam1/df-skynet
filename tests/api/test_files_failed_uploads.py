from unittest.mock import MagicMock, patch
from uuid import uuid4
import pytest
import pytest_asyncio
from sqlalchemy import select
from middlewares.lang import resolve_message
from services.mysql.factory.df_engine_features import DfEngineFeaturesFactory
from services.mysql.factory.df_engine_generation_uploads import DfEngineGenerationUploadsFactory
from services.mysql.factory.df_engine_generations import DfEngineGenerationsFactory
from services.mysql.factory.df_engine_generation_results import DfEngineGenerationResultsFactory
from services.mysql.factory.df_engine_menus import DfEngineMenusFactory
from services.mysql.factory.df_engine_model_options import DfEngineModelOptionsFactory
from services.mysql.model import DfEngineGenerations
from services.mysql.model.df_engine_generation_uploads import UploadStatuses
from services.mysql.model.df_engine_generations import GenerationKinds, GenerationStatuses
from services.redis import CacheKeys, client as redis_client

LIST_URL = "/api/files/failed-uploads"
DELAY = "apps.controller.files.udin_uploader.delay"
OVERRIDE = "apps.controller.files.has_override"


@pytest.fixture
def list_url(project_task) -> str:
    return f"{LIST_URL}/{project_task.project.uid}"


def _url(generation_uid) -> str:
    return f"{LIST_URL}/{generation_uid}"


@pytest_asyncio.fixture
async def generation_fks(user_id) -> dict:
    model_option = DfEngineModelOptionsFactory.create()
    menu = DfEngineMenusFactory.create(created_by=int(user_id), df_engine_menu_feature_mapping=None)
    feature = DfEngineFeaturesFactory.create(created_by=int(user_id), df_engine_feature_prompt_mapping=None)
    return {"model_id": model_option.id, "menu_id": menu.id, "feature_id": feature.id}


@pytest.fixture
def make(project_task, generation_fks):
    def _make(created_by, upload_status=UploadStatuses.failed, kind=GenerationKinds.image, **over):
        generation = DfEngineGenerationsFactory.create(
            project_id=project_task.project_id,
            task_id=project_task.id,
            created_by=int(created_by),
            sourceable_id=1,
            kind=kind,
            status=GenerationStatuses.failed,
            **{**generation_fks, **over},
        )
        DfEngineGenerationUploadsFactory.create(
            generation_id=generation.id,
            upload_status=upload_status,
            needs_reconciliation=True,
            sweep_attempts=12,
        )
        return generation

    return _make


@pytest_asyncio.fixture(autouse=True)
async def _release_locks():
    yield
    redis = redis_client()
    async for key in redis.scan_iter(match="generation_reupload_lock:*"):
        await redis.delete(key)


async def _status_of(db_session, generation_id):
    await db_session.commit()  # end the repeatable-read snapshot opened by earlier fixtures
    return (
        await db_session.execute(select(DfEngineGenerations.status).where(DfEngineGenerations.id == generation_id))
    ).scalar_one()


# ---------------------------------------------------------------- GET


@pytest.mark.asyncio
async def test_list_returns_only_failed_uploads_as_flat_variants(list_url, authed_client, user_id, make):
    """Only `upload_status=failed` rows are listed, as a flat list of GenerationVariant dicts with no path."""
    failed = make(user_id)
    make(user_id, upload_status=UploadStatuses.pending)
    make(user_id, upload_status=UploadStatuses.success)

    resp = await authed_client.call("GET", list_url)
    assert resp.status_code == 200
    data = resp.json()["data"]
    mine = [row for row in data if row["generation_uid"] == str(failed.uid)]
    assert len(mine) == 1
    assert mine[0]["path"] is None
    assert mine[0]["kind"] == "image"
    assert mine[0]["prompt"] == failed.prompt
    assert "variants" not in mine[0] and "references" not in mine[0]


@pytest.mark.asyncio
async def test_list_excludes_pending_and_success(list_url, authed_client, user_id, make):
    pending = make(user_id, upload_status=UploadStatuses.pending)
    success = make(user_id, upload_status=UploadStatuses.success)

    resp = await authed_client.call("GET", list_url)
    uids = {row["generation_uid"] for row in resp.json()["data"]}
    assert str(pending.uid) not in uids and str(success.uid) not in uids


@pytest.mark.asyncio
async def test_list_filters(authed_client, user_id, make, project_task, list_url):
    image = make(user_id, prompt="prompt-only-needle")
    video = make(user_id, kind=GenerationKinds.video, prompt="other")

    async def uids(**params):
        resp = await authed_client.call("GET", list_url, params=params)
        assert resp.status_code == 200
        return {row["generation_uid"] for row in resp.json()["data"]}

    assert {str(image.uid), str(video.uid)} <= await uids()  # image and video are both listed
    assert str(image.uid) in await uids(search="prompt-only-needle")  # prompt
    assert str(video.uid) not in await uids(search="prompt-only-needle")
    model_name = f"UniqueModel-{uuid4().hex[:8]}"
    other = make(user_id, model_id=DfEngineModelOptionsFactory.create(name=model_name).id)
    assert str(other.uid) in await uids(search=model_name)  # model name
    assert str(video.uid) not in await uids(search=model_name)
    assert {str(image.uid), str(video.uid)} <= await uids(search=project_task.name)  # task name
    assert {str(image.uid), str(video.uid)} <= await uids()
    assert {str(image.uid), str(video.uid)} <= await uids(task_uid=project_task.uid)  # task_id + project_id
    bad = await authed_client.call("GET", list_url, params={"task_uid": "nope"}, raise_for_status=False)
    assert bad.status_code == 422


@pytest.mark.asyncio
async def test_list_only_returns_image_image_edit_and_video(authed_client, user_id, make, list_url):
    wanted = [make(user_id, kind=k) for k in (GenerationKinds.image, GenerationKinds.image_edit, GenerationKinds.video)]
    other = make(user_id, kind=GenerationKinds.chat)

    resp = await authed_client.call("GET", list_url)
    uids = {row["generation_uid"] for row in resp.json()["data"]}
    assert {str(g.uid) for g in wanted} <= uids
    assert str(other.uid) not in uids
    # `kind` is no longer a query param: an unknown one is ignored, not validated
    assert (await authed_client.call("GET", list_url, params={"kind": "chat"})).status_code == 200


@pytest.mark.asyncio
async def test_list_is_scoped_to_the_project_in_the_path(authed_client, user_id, make):
    generation = make(user_id)

    resp = await authed_client.call("GET", f"{LIST_URL}/{uuid4()}", raise_for_status=False)
    assert resp.status_code == 404
    assert str(generation.uid) not in {r["generation_uid"] for r in resp.json().get("data") or []}


@pytest.mark.asyncio
async def test_list_unknown_task_uid_is_404(authed_client, list_url):
    resp = await authed_client.call("GET", list_url, params={"task_uid": str(uuid4())}, raise_for_status=False)
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_list_task_uid_resolves_to_project_and_task_ids(authed_client, list_url, project_task):
    with patch("apps.controller.files.get_failed_upload_generations", return_value=[]) as fetch:
        await authed_client.call("GET", list_url, params={"task_uid": str(project_task.uid)})
    assert (
        fetch.call_args.kwargs.items()
        >= {"project_id": project_task.project_id, "task_id": project_task.id, "song_id": None}.items()
    )


@pytest.mark.asyncio
async def test_list_song_uid_resolves_to_project_and_song_ids(authed_client, list_url, project_task):
    song = {"id": 99, "is_song": True, "project_id": project_task.project_id}
    with (
        patch("apps.controller.files.get_project_task", return_value=song),
        patch("apps.controller.files.get_failed_upload_generations", return_value=[]) as fetch,
    ):
        await authed_client.call("GET", list_url, params={"task_uid": str(uuid4())})
    assert (
        fetch.call_args.kwargs.items()
        >= {"project_id": project_task.project_id, "task_id": None, "song_id": 99}.items()
    )


@pytest.mark.asyncio
async def test_list_scopes_to_owner_unless_override(list_url, authed_client, user_id, other_user_id, make):
    mine = make(user_id)
    theirs = make(other_user_id)

    with patch(OVERRIDE, return_value=False):
        uids = {row["generation_uid"] for row in (await authed_client.call("GET", list_url)).json()["data"]}
    assert str(mine.uid) in uids and str(theirs.uid) not in uids

    with patch(OVERRIDE, return_value=True):
        uids = {row["generation_uid"] for row in (await authed_client.call("GET", list_url)).json()["data"]}
    assert {str(mine.uid), str(theirs.uid)} <= uids


@pytest.mark.asyncio
async def test_list_error_returns_500(authed_client, list_url):
    with patch("apps.controller.files.get_failed_upload_generations", side_effect=RuntimeError("boom")):
        resp = await authed_client.call("GET", list_url, raise_for_status=False)
    assert resp.status_code == 500


# ---------------------------------------------------------------- PATCH


@pytest.mark.asyncio
async def test_reupload_queues_uploader_directly(authed_client, user_id, make, db_session):
    """200; dispatches the uploader once, takes the lock, shows the generation as processing, keeps sweep_attempts."""
    generation = make(user_id)

    with patch(DELAY, MagicMock()) as delay:
        resp = await authed_client.call("PATCH", _url(generation.uid), raise_for_status=False)

    assert resp.status_code == 200
    assert resp.json()["message"] == resolve_message("reupload_queued", "en")
    assert resp.json()["data"]["generation_uid"] == str(generation.uid)
    delay.assert_called_once_with(generation.id, int(user_id))
    assert await _status_of(db_session, generation.id) == GenerationStatuses.processing
    assert await redis_client().get(CacheKeys().generation_reupload_lock(generation.id)) is not None


@pytest.mark.asyncio
async def test_reupload_not_found(authed_client):
    resp = await authed_client.call("PATCH", _url(uuid4()), raise_for_status=False)
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_reupload_invalid_uuid(authed_client):
    assert (await authed_client.call("PATCH", _url("not-a-uuid"), raise_for_status=False)).status_code == 422


@pytest.mark.asyncio
async def test_reupload_not_creator_is_refused_but_override_allowed(authed_client, other_user_id, make):
    generation = make(other_user_id)

    with patch(OVERRIDE, return_value=False), patch(DELAY, MagicMock()) as delay:
        resp = await authed_client.call("PATCH", _url(generation.uid), raise_for_status=False)
    assert resp.status_code == 403
    delay.assert_not_called()

    with patch(OVERRIDE, return_value=True), patch(DELAY, MagicMock()) as delay:
        resp = await authed_client.call("PATCH", _url(generation.uid), raise_for_status=False)
    assert resp.status_code == 200
    delay.assert_called_once_with(generation.id, int(other_user_id))


@pytest.mark.asyncio
@pytest.mark.parametrize("upload_status", [UploadStatuses.pending, UploadStatuses.success])
async def test_reupload_requires_failed_upload(authed_client, user_id, make, upload_status):
    generation = make(user_id, upload_status=upload_status)

    with patch(DELAY, MagicMock()) as delay:
        resp = await authed_client.call("PATCH", _url(generation.uid), raise_for_status=False)
    assert resp.status_code == 422
    delay.assert_not_called()


@pytest.mark.asyncio
async def test_reupload_second_call_while_running_is_409(authed_client, user_id, make):
    generation = make(user_id)

    with patch(DELAY, MagicMock()) as delay:
        assert (await authed_client.call("PATCH", _url(generation.uid), raise_for_status=False)).status_code == 200
        resp = await authed_client.call("PATCH", _url(generation.uid), raise_for_status=False)
    assert resp.status_code == 409
    delay.assert_called_once()


@pytest.mark.asyncio
async def test_reupload_dispatch_failure_restores_status_and_lock(authed_client, user_id, make, db_session):
    generation = make(user_id)

    with patch(DELAY, MagicMock(side_effect=RuntimeError("broker down"))):
        resp = await authed_client.call("PATCH", _url(generation.uid), raise_for_status=False)

    assert resp.status_code == 500
    assert await _status_of(db_session, generation.id) == GenerationStatuses.failed
    assert await redis_client().get(CacheKeys().generation_reupload_lock(generation.id)) is None


@pytest.mark.asyncio
async def test_dto_song_id_filter(db_session, user_id, make, project_task):
    from services.dto import ConnectionContext
    from services.dto.asynced.generation_files import get_failed_upload_generations

    make(user_id)
    ctx = ConnectionContext(db_session, redis_client(), CacheKeys())
    assert (
        await get_failed_upload_generations(ctx, int(user_id), True, project_task.project_id, song_id=2**31 - 1) == []
    )


@pytest.mark.asyncio
async def test_list_task_of_another_project_is_404(authed_client, list_url, project_task):
    foreign = {"id": 99, "is_song": False, "project_id": project_task.project_id + 1}
    with patch("apps.controller.files.get_project_task", return_value=foreign):
        resp = await authed_client.call("GET", list_url, params={"task_uid": str(uuid4())}, raise_for_status=False)
    assert resp.status_code == 404
