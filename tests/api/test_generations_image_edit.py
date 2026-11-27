from uuid import uuid4
import pytest
import pytest_asyncio
from sqlalchemy import select, update
from middlewares.lang import resolve_message
from services.mysql.factory.df_engine_generations import DfEngineGenerationsFactory
from services.mysql.factory.df_engine_generation_results import DfEngineGenerationResultsFactory
from services.mysql.factory.df_engine_upload_files import DfEngineUploadFilesFactory
from services.mysql.model import DfEngineGenerationReferences, DfEngineGenerations, DfEngineUploadFileReferences
from services.mysql.model.df_engine_generations import GenerationKinds
from services.mysql.model.df_engine_model_options import DfEngineModelOptions
from services.mysql.model.df_engine_upload_files import UploadFileTypes
from services.repository.generation_results import GenerationResultRepository
from tests.generation_fixtures import (  # noqa: F401  (fixtures)
    fake_generation_backends,
    generation_menu_feature,
    generation_project_settings,
    guardrail,
    image_model,
    override_repo,
    pic_api_key,
    pic_employee_id,
    project_lead,
)

URL = "/api/generations/image-edit"

# Same exclude set the endpoint's `GenerationResultRecord(...).model_dump(exclude=...)` uses,
# so the response must always have exactly the complement of these keys.
EXCLUDED_KEYS = {"flag_created_at", "flag_favourited_at", "flag_archieved_at", "version", "updated_at", "parameter"}


def _url(file_uid):
    return f"{URL}/{file_uid}"


@pytest_asyncio.fixture
async def source_root(project_task, user_id, image_model, generation_menu_feature):
    """A pre-existing, standalone (root, no parent) generated image owned by the
    authenticated user - the file `POST /generations/image-edit/{file_uid}` targets."""
    menu, feature = generation_menu_feature
    generation = DfEngineGenerationsFactory.create(
        project_id=project_task.project_id,
        task_id=project_task.id,
        created_by=int(user_id),
        sourceable_id=1,
        model_id=image_model.id,
        menu_id=menu.id,
        feature_id=feature.id,
    )
    return DfEngineGenerationResultsFactory.create(generation_id=generation.id, created_by=int(user_id), is_main=True)


@pytest_asyncio.fixture
async def source_child(source_root, project_task, user_id, image_model, generation_menu_feature):
    """A non-root version (version 2, parented to `source_root`) of the same family."""
    menu, feature = generation_menu_feature
    generation = DfEngineGenerationsFactory.create(
        project_id=project_task.project_id,
        task_id=project_task.id,
        created_by=int(user_id),
        sourceable_id=1,
        model_id=image_model.id,
        menu_id=menu.id,
        feature_id=feature.id,
    )
    return DfEngineGenerationResultsFactory.create(
        generation_id=generation.id, created_by=int(user_id), is_main=False, parent_id=source_root.id, version=2
    )


def _payload(menu, feature, model, **overrides):
    return {
        "prompt": "make the sky more dramatic",
        "model_uid": str(model.uid),
        "menu_uid": str(menu.uid),
        "feature_uid": str(feature.uid),
        "references": [],
        "parameter": {},
        **overrides,
    }


@pytest.mark.asyncio
async def test_editing_a_root_file_sets_parent_id_to_its_own_id(
    authed_client,
    source_root,
    generation_menu_feature,
    image_model,
    pic_api_key,
    generation_project_settings,
    fake_generation_backends,
):
    """200 OK; editing a root (no parent) file chains the new generation onto that
    root's own id, and dispatches the fake Celery task exactly once."""
    menu, feature = generation_menu_feature
    resp = await authed_client.call("POST", _url(source_root.uid), json=_payload(menu, feature, image_model))
    assert resp.status_code == 200
    assert len(fake_generation_backends) == 1

    body = resp.json()["data"]
    assert body["parent_id"] == source_root.id
    assert body["kind"] == "image_edit"


@pytest.mark.asyncio
async def test_editing_a_child_file_chains_to_its_root_not_itself(
    authed_client,
    source_child,
    source_root,
    generation_menu_feature,
    image_model,
    pic_api_key,
    generation_project_settings,
    fake_generation_backends,
):
    """200 OK; editing an already-non-root version still resolves `parent_id` to the
    family's root id, not to the edited version's own id - lineage stays one level deep."""
    menu, feature = generation_menu_feature
    resp = await authed_client.call("POST", _url(source_child.uid), json=_payload(menu, feature, image_model))
    assert resp.status_code == 200
    assert resp.json()["data"]["parent_id"] == source_root.id


@pytest.mark.asyncio
async def test_response_format_matches_the_plain_generate_endpoint(
    authed_client,
    source_root,
    generation_menu_feature,
    image_model,
    pic_api_key,
    generation_project_settings,
    fake_generation_backends,
):
    """200 OK; the edit endpoint's response carries exactly the same key set as
    `POST /generations/{task_uid}` (both build the same `GenerationResultRecord`
    with the same exclude set) - only `parent_id` is actually populated here."""
    menu, feature = generation_menu_feature
    resp = await authed_client.call("POST", _url(source_root.uid), json=_payload(menu, feature, image_model))
    body = resp.json()["data"]
    expected_keys = {
        "id",
        "kind",
        "file_uid",
        "generation_uid",
        "parent_id",
        "name",
        "is_main",
        "path",
        "size",
        "created_at",
        "favourited_at",
        "archieved_at",
        "icon",
        "color",
        "status",
        "creator",
        "cost_usd",
        "cost_idr",
        "model",
        "raw_prompt",
        "finalized_prompt",
        "action",
        "type",
    }
    assert set(body.keys()) == expected_keys
    assert not (set(body.keys()) & EXCLUDED_KEYS)


@pytest.mark.asyncio
async def test_n_other_than_one_is_rejected(
    authed_client,
    source_root,
    generation_menu_feature,
    image_model,
    pic_api_key,
    generation_project_settings,
    fake_generation_backends,
):
    """422; image-edit generations must always produce exactly one result, so `n` != 1 is rejected."""
    menu, feature = generation_menu_feature
    resp = await authed_client.call(
        "POST",
        _url(source_root.uid),
        json=_payload(menu, feature, image_model, parameter={"n": 2}),
        raise_for_status=False,
    )
    assert resp.status_code == 422
    assert len(fake_generation_backends) == 0


@pytest.mark.asyncio
async def test_reference_count_matches_requested_file_not_all_its_siblings(
    authed_client,
    project_task,
    user_id,
    generation_menu_feature,
    image_model,
    pic_api_key,
    generation_project_settings,
    fake_generation_backends,
    db_session,
):
    """200 OK; editing one file whose generation produced 3 sibling results (n=3) must
    create exactly 1 `DfEngineGenerationReferences` row (the edited file itself),
    not 3 - regression test for the `get_generation_files` over-fetch bug."""
    menu, feature = generation_menu_feature
    batch_generation = DfEngineGenerationsFactory.create(
        project_id=project_task.project_id,
        task_id=project_task.id,
        created_by=int(user_id),
        sourceable_id=1,
        model_id=image_model.id,
        menu_id=menu.id,
        feature_id=feature.id,
    )
    siblings = [
        DfEngineGenerationResultsFactory.create(
            generation_id=batch_generation.id, created_by=int(user_id), is_main=(i == 0)
        )
        for i in range(3)
    ]
    target = siblings[0]

    resp = await authed_client.call("POST", _url(target.uid), json=_payload(menu, feature, image_model))
    assert resp.status_code == 200

    new_generation_id = select(DfEngineGenerationReferences).where(
        DfEngineGenerationReferences.result_id.in_([s.id for s in siblings])
    )
    rows = (await db_session.execute(new_generation_id)).scalars().all()
    assert len(rows) == 1
    assert rows[0].result_id == target.id


@pytest.mark.asyncio
async def test_requires_auth(client, source_root):
    """401 when the request carries no bearer token."""
    resp = await client.call(
        "POST", _url(source_root.uid), json={"prompt": "x", "parameter": {}}, raise_for_status=False
    )
    assert resp.status_code == 401


@pytest_asyncio.fixture
async def foreign_source(project_task, other_user_id, image_model, generation_menu_feature):
    """A generated image owned by someone else."""
    menu, feature = generation_menu_feature
    generation = DfEngineGenerationsFactory.create(
        project_id=project_task.project_id,
        task_id=project_task.id,
        created_by=other_user_id,
        sourceable_id=1,
        model_id=image_model.id,
        menu_id=menu.id,
        feature_id=feature.id,
    )
    return DfEngineGenerationResultsFactory.create(generation_id=generation.id, created_by=other_user_id, is_main=True)


@pytest.mark.asyncio
async def test_editing_someone_elses_file_without_override_role_is_refused(
    authed_client, foreign_source, generation_menu_feature, image_model, as_roles, fake_generation_backends
):
    """403 generated_file_edit_not_permitted; a plain user cannot edit another user's file and nothing is dispatched."""
    as_roles(["staff"])
    menu, feature = generation_menu_feature
    resp = await authed_client.call(
        "POST", _url(foreign_source.uid), json=_payload(menu, feature, image_model), raise_for_status=False
    )
    assert resp.status_code == 403
    assert resp.json()["message"] == resolve_message("generated_file_edit_not_permitted", "en")
    assert resp.json()["error"] is None
    assert fake_generation_backends == []


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", [GenerationKinds.video, GenerationKinds.element, GenerationKinds.storyboard])
async def test_editing_a_generation_that_is_not_image_or_image_edit_is_rejected(
    authed_client,
    project_task,
    user_id,
    image_model,
    generation_menu_feature,
    fake_generation_backends,
    kind,
):
    """422 file_edit_image_only; only `image` / `image_edit` generations can be edited, and nothing is dispatched."""
    menu, feature = generation_menu_feature
    generation = DfEngineGenerationsFactory.create(
        project_id=project_task.project_id,
        task_id=project_task.id,
        created_by=int(user_id),
        sourceable_id=1,
        model_id=image_model.id,
        menu_id=menu.id,
        feature_id=feature.id,
        kind=kind,
    )
    source = DfEngineGenerationResultsFactory.create(generation_id=generation.id, created_by=int(user_id), is_main=True)
    resp = await authed_client.call(
        "POST", _url(source.uid), json=_payload(menu, feature, image_model), raise_for_status=False
    )
    assert resp.status_code == 422
    assert resp.json()["message"] == resolve_message("file_edit_image_only", "en")
    assert resp.json()["error"] is None
    assert fake_generation_backends == []


@pytest.mark.asyncio
async def test_editing_a_file_that_does_not_exist_is_404(
    authed_client, generation_menu_feature, image_model, as_roles, fake_generation_backends
):
    """404 file_not_found; an unknown file uid is still reported as missing, not as a permission problem."""
    as_roles(["staff"])
    menu, feature = generation_menu_feature
    resp = await authed_client.call(
        "POST", _url(uuid4()), json=_payload(menu, feature, image_model), raise_for_status=False
    )
    assert resp.status_code == 404
    assert fake_generation_backends == []


@pytest.mark.asyncio
async def test_editing_someone_elses_file_with_override_role_belongs_to_the_editor(
    authed_client,
    foreign_source,
    generation_menu_feature,
    image_model,
    pic_api_key,
    generation_project_settings,
    fake_generation_backends,
    as_roles,
    user_id,
    db_session,
):
    """200 OK; an override role can edit another user's file, the new version is created by the editor and chains to the original."""
    as_roles(["director"])
    menu, feature = generation_menu_feature
    resp = await authed_client.call("POST", _url(foreign_source.uid), json=_payload(menu, feature, image_model))
    assert resp.status_code == 200, resp.text
    assert len(fake_generation_backends) == 1
    body = resp.json()["data"]
    assert body["parent_id"] == foreign_source.id and body["kind"] == "image_edit"
    assert body["creator"]["user_id"] == int(user_id)


@pytest_asyncio.fixture
async def image_model_two_refs(db_session, image_model):
    image_model.supported_parameters = {"input_references": {"max": 2}}
    await db_session.execute(
        update(DfEngineModelOptions)
        .where(DfEngineModelOptions.id == image_model.id)
        .values(supported_parameters=image_model.supported_parameters)
    )
    await db_session.commit()


@pytest_asyncio.fixture
async def make_upload(project_task, user_id, other_user_id):
    def _make(owner="me", **overrides):
        data = {
            "project_id": project_task.project_id,
            "task_id": project_task.id,
            "created_by": int(user_id) if owner == "me" else other_user_id,
            **overrides,
        }
        return DfEngineUploadFilesFactory.create(**data)

    return _make


@pytest.mark.asyncio
async def test_editing_an_upload_starts_a_new_plain_generation_with_the_upload_as_reference(
    authed_client,
    image_model_two_refs,
    make_upload,
    source_root,
    generation_menu_feature,
    image_model,
    pic_api_key,
    generation_project_settings,
    fake_generation_backends,
    db_session,
):
    """200 OK; upload source -> kind `image`, parent_id None, upload stored in upload references and extra generated refs in generation references."""
    upload = make_upload()
    menu, feature = generation_menu_feature
    payload = _payload(
        menu,
        feature,
        image_model,
        source="upload",
        references=[{"type": "generated", "file_uid": str(source_root.uid)}],
    )
    resp = await authed_client.call("POST", _url(upload.uid), json=payload, raise_for_status=False)
    assert resp.status_code == 200, resp.text
    assert len(fake_generation_backends) == 1
    body = resp.json()["data"]
    assert body["parent_id"] is None and body["kind"] == "image"

    generation = (
        (await db_session.execute(select(DfEngineGenerations).where(DfEngineGenerations.uid == body["generation_uid"])))
        .scalars()
        .one()
    )
    upload_refs = (
        (
            await db_session.execute(
                select(DfEngineUploadFileReferences.file_id).where(
                    DfEngineUploadFileReferences.generation_id == generation.id
                )
            )
        )
        .scalars()
        .all()
    )
    generated_refs = (
        (
            await db_session.execute(
                select(DfEngineGenerationReferences.result_id).where(
                    DfEngineGenerationReferences.generation_id == generation.id
                )
            )
        )
        .scalars()
        .all()
    )
    assert list(upload_refs) == [upload.id] and list(generated_refs) == [source_root.id]


@pytest.mark.asyncio
async def test_editing_someone_elses_upload_without_override_role_is_refused(
    authed_client, make_upload, generation_menu_feature, image_model, as_roles, fake_generation_backends
):
    """403 uploaded_file_edit_not_permitted; nothing is dispatched."""
    as_roles(["staff"])
    menu, feature = generation_menu_feature
    resp = await authed_client.call(
        "POST",
        _url(make_upload(owner="other").uid),
        json=_payload(menu, feature, image_model, source="upload"),
        raise_for_status=False,
    )
    assert resp.status_code == 403
    assert resp.json()["message"] == resolve_message("uploaded_file_edit_not_permitted", "en")
    assert fake_generation_backends == []


@pytest.mark.asyncio
async def test_editing_someone_elses_upload_with_override_role_is_allowed(
    authed_client,
    make_upload,
    generation_menu_feature,
    image_model,
    pic_api_key,
    generation_project_settings,
    fake_generation_backends,
    as_roles,
):
    as_roles(["director"])
    menu, feature = generation_menu_feature
    resp = await authed_client.call(
        "POST",
        _url(make_upload(owner="other").uid),
        json=_payload(menu, feature, image_model, source="upload"),
        raise_for_status=False,
    )
    assert resp.status_code == 200, resp.text
    assert len(fake_generation_backends) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "overrides, key",
    [({"task_id": None}, "file_edit_task_required"), ({"type": UploadFileTypes.folder}, "file_edit_image_only")],
)
async def test_upload_without_task_or_not_an_image_is_rejected(
    authed_client,
    make_upload,
    generation_menu_feature,
    image_model,
    pic_api_key,
    generation_project_settings,
    fake_generation_backends,
    overrides,
    key,
):
    menu, feature = generation_menu_feature
    resp = await authed_client.call(
        "POST",
        _url(make_upload(**overrides).uid),
        json=_payload(menu, feature, image_model, source="upload"),
        raise_for_status=False,
    )
    assert resp.status_code == 422
    assert resp.json()["message"] == resolve_message(key, "en")
    assert fake_generation_backends == []


@pytest.mark.asyncio
async def test_editing_a_missing_upload_is_404(authed_client, generation_menu_feature, image_model):
    menu, feature = generation_menu_feature
    resp = await authed_client.call(
        "POST", _url(uuid4()), json=_payload(menu, feature, image_model, source="upload"), raise_for_status=False
    )
    assert resp.status_code == 404


def _status_change(task_status=1, song_status=None, project_status=1):
    """Edits the source file's record: its project status, and the status of its task or song."""

    def change(record):
        generation = record["generation"]
        generation["project"]["status"] = project_status
        generation["task"]["status"] = task_status
        if song_status is not None:
            generation.update(task_id=None, song_id=1, task=None)
            generation["song"] = {"entertainment_task_songs": [{"status": song_status}]}

    return change


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "statuses, key",
    [
        ({"task_status": 4}, "project_task_already_completed"),
        ({"song_status": 6}, "song_task_already_completed"),
        ({"project_status": 2}, "project_not_ongoing"),
    ],
)
async def test_editing_is_refused_for_completed_task_or_inactive_project(
    authed_client,
    source_root,
    generation_menu_feature,
    image_model,
    pic_api_key,
    fake_generation_backends,
    override_repo,
    statuses,
    key,
):
    """422; a completed task/song or a non-ongoing project blocks the edit before anything is dispatched."""
    override_repo(GenerationResultRepository, "get_generation_file", _status_change(**statuses))
    menu, feature = generation_menu_feature
    resp = await authed_client.call(
        "POST", _url(source_root.uid), json=_payload(menu, feature, image_model), raise_for_status=False
    )
    assert resp.status_code == 422
    assert resp.json()["message"] == resolve_message(key, "en")
    assert fake_generation_backends == []
