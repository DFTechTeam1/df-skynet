import pytest
import pytest_asyncio
from types import SimpleNamespace
from sqlalchemy import select
from middlewares.lang import resolve_message
from services.mysql.factory.df_engine_model_options import DfEngineModelOptionsFactory
from services.mysql.model import DfEngineGenerations, DfEngineGuardrailValidations
from services.mysql.model.df_engine_model_options import ModelUsageTypes
from tests.generation_fixtures import (  # noqa: F401  (fixtures)
    fake_generation_backends,
    generation_menu_feature,
    generation_project_settings,
    guardrail,
    image_model,
    payload as _payload,
    pic_api_key,
    pic_employee_id,
    project_lead,
)

URL = "/api/generations"


def _url(task_uid):
    return f"{URL}/{task_uid}"


@pytest_asyncio.fixture
async def video_model():
    """A usable video model with one resolution, ratio, duration and frame type."""
    return DfEngineModelOptionsFactory.create(
        type=ModelUsageTypes.video,
        is_enabled=True,
        is_available=True,
        deleted_at=None,
        supported_resolutions=["720p"],
        supported_aspect_ratios=["16:9"],
        supported_sizes=["1280x720"],
        supported_durations=[5],
        supported_frame_images=["first_frame"],
    )


async def _latest_generation(db_session, task_id):
    await db_session.commit()  # start a new snapshot, so rows committed by the endpoint are visible
    query = select(DfEngineGenerations).where(DfEngineGenerations.task_id == task_id)
    return (await db_session.execute(query.order_by(DfEngineGenerations.id.desc()).limit(1))).scalars().one()


@pytest.mark.asyncio
async def test_image_generation_happy_path_dispatches_task_and_returns_galleries(
    authed_client,
    project_task,
    generation_menu_feature,
    image_model,
    pic_api_key,
    generation_project_settings,
    fake_generation_backends,
):
    """200 OK; a valid image request creates the generation, dispatches the fake
    Celery task exactly once, and returns only the newly created record as a
    single object (the FE is expected to refetch the user-galleries endpoint
    for the full list)."""
    menu, feature = generation_menu_feature
    resp = await authed_client.call("POST", _url(project_task.uid), json=_payload(menu, feature, image_model))
    assert resp.status_code == 200
    assert len(fake_generation_backends) == 1

    body = resp.json()["data"]
    assert isinstance(body, dict)
    assert body["type"] == "image"
    assert body["is_main"] is None
    assert "variants" not in body


@pytest.mark.asyncio
async def test_response_is_the_new_generation_not_a_prior_one(
    authed_client,
    project_task,
    generation_menu_feature,
    image_model,
    pic_api_key,
    generation_project_settings,
    fake_generation_backends,
):
    """200 OK; a second generation on the same task returns only itself — an earlier
    generation on that task must not be reflected in the response."""
    menu, feature = generation_menu_feature
    first = await authed_client.call("POST", _url(project_task.uid), json=_payload(menu, feature, image_model))
    first_uid = first.json()["data"]["generation_uid"]

    second = await authed_client.call("POST", _url(project_task.uid), json=_payload(menu, feature, image_model))
    assert second.json()["data"]["generation_uid"] != first_uid


def _video_payload(menu, feature, model, **overrides):
    return _payload(
        menu,
        feature,
        model,
        type="video",
        parameter={"resolution": "720p", "aspect_ratio": "16:9", "duration": 5},
        **overrides,
    )


@pytest.mark.asyncio
async def test_video_generation_happy_path_dispatches_task_and_returns_galleries(
    authed_client,
    project_task,
    generation_menu_feature,
    video_model,
    pic_api_key,
    generation_project_settings,
    fake_generation_backends,
):
    """200 OK; a valid video request creates the generation, dispatches the fake
    Celery video task exactly once, and returns the newly created record."""
    menu, feature = generation_menu_feature
    resp = await authed_client.call("POST", _url(project_task.uid), json=_video_payload(menu, feature, video_model))
    assert resp.status_code == 200
    assert len(fake_generation_backends) == 1

    body = resp.json()["data"]
    assert isinstance(body, dict)
    assert body["type"] == "video"
    assert body["is_main"] is None
    assert "variants" not in body


@pytest.mark.asyncio
async def test_video_generation_invalid_parameter_is_422(
    authed_client,
    project_task,
    generation_menu_feature,
    video_model,
    pic_api_key,
    generation_project_settings,
    fake_generation_backends,
    guardrail,
):
    """422 parameter_required; a video request missing a required parameter is refused before the paid
    guardrail, and nothing is dispatched."""
    menu, feature = generation_menu_feature
    body = _payload(menu, feature, video_model, type="video")
    resp = await authed_client.call("POST", _url(project_task.uid), json=body, raise_for_status=False)
    assert resp.status_code == 422
    assert resp.json()["message"] == resolve_message("parameter_required", "en").format(parameter="resolution")
    assert resp.json()["error"] is None
    assert fake_generation_backends == [] and guardrail.calls == []


@pytest.mark.asyncio
async def test_unknown_menu_is_404(
    authed_client,
    project_task,
    generation_menu_feature,
    image_model,
    pic_api_key,
    generation_project_settings,
    fake_generation_backends,
):
    """404 menu_not_found when menu_uid matches no menu."""
    _menu, feature = generation_menu_feature
    unmapped_menu = SimpleNamespace(uid="00000000-0000-0000-0000-000000000000")
    body = _payload(unmapped_menu, feature, image_model)
    resp = await authed_client.call("POST", _url(project_task.uid), json=body, raise_for_status=False)
    assert resp.status_code == 404
    assert resp.json()["message"] == resolve_message("menu_not_found", "en")


@pytest.mark.asyncio
async def test_unknown_reference_is_reported_by_its_index(
    authed_client,
    project_task,
    generation_menu_feature,
    image_model,
    pic_api_key,
    generation_project_settings,
    fake_generation_backends,
    guardrail,
):
    """422 reference_check_failed, keyed by the reference's position, before the paid guardrail."""
    menu, feature = generation_menu_feature
    references = [{"type": "upload", "file_uid": "00000000-0000-0000-0000-000000000001"}]
    body = _payload(menu, feature, image_model, references=references)
    resp = await authed_client.call("POST", _url(project_task.uid), json=body, raise_for_status=False)
    assert resp.status_code == 422
    assert resp.json()["message"] == resolve_message("reference_check_failed", "en")
    assert resp.json()["error"] == {"references.0": [resolve_message("reference_upload_not_found", "en")]}
    assert fake_generation_backends == [] and guardrail.calls == []


@pytest.mark.asyncio
async def test_guardrail_rejection_saves_a_failed_generation(
    authed_client,
    project_task,
    generation_menu_feature,
    image_model,
    pic_api_key,
    generation_project_settings,
    fake_generation_backends,
    guardrail,
    db_session,
):
    """422; the refused prompt is saved as a failed generation with its guardrail record, and not queued."""
    guardrail.flags["nfsw"] = True
    menu, feature = generation_menu_feature
    body = _payload(menu, feature, image_model)
    resp = await authed_client.call("POST", _url(project_task.uid), json=body, raise_for_status=False)
    assert resp.status_code == 422
    assert resp.json()["message"] == resolve_message("prompt_nsfw_detected", "en")
    assert fake_generation_backends == []

    row = await _latest_generation(db_session, project_task.id)
    assert (row.status, row.status_code) == ("failed", 400)
    validation = select(DfEngineGuardrailValidations).where(
        DfEngineGuardrailValidations.sourceable_type == "DfEngineGenerations",
        DfEngineGuardrailValidations.sourceable_id == row.id,
    )
    assert (await db_session.execute(validation)).scalars().one()


@pytest.mark.asyncio
async def test_guardrail_without_an_assistant_model_is_422(
    authed_client,
    project_task,
    generation_menu_feature,
    image_model,
    pic_api_key,
    generation_project_settings,
    fake_generation_backends,
    guardrail,
):
    """422 guardrail_assistant_model_not_configured; active rules need an assistant model."""
    await guardrail.save(None)
    menu, feature = generation_menu_feature
    body = _payload(menu, feature, image_model)
    resp = await authed_client.call("POST", _url(project_task.uid), json=body, raise_for_status=False)
    assert resp.status_code == 422
    assert resp.json()["message"] == resolve_message("guardrail_assistant_model_not_configured", "en")
    assert fake_generation_backends == [] and guardrail.calls == []


@pytest.mark.asyncio
async def test_requires_auth(client, project_task):
    """401 when the request carries no bearer token."""
    resp = await client.call(
        "POST", _url(project_task.uid), json={"prompt": "x", "parameter": {}}, raise_for_status=False
    )
    assert resp.status_code == 401


@pytest_asyncio.fixture
async def two_frame_video_model():
    """Video model supporting both first_frame and last_frame (the only kind that accepts a frame color)."""
    return DfEngineModelOptionsFactory.create(
        type=ModelUsageTypes.video,
        is_enabled=True,
        is_available=True,
        deleted_at=None,
        supported_resolutions=["720p"],
        supported_aspect_ratios=["16:9"],
        supported_sizes=["1280x720"],
        supported_durations=[5],
        supported_frame_images=["first_frame", "last_frame"],
    )


FRAME_URL = "https://example.com/first.png"


def _color_payload(menu, feature, model, frames, color="#4cfb2b"):
    return _video_payload(
        menu,
        feature,
        model,
        frame_images=[{"frame_type": t, "type": "diva", "diva_url": FRAME_URL} for t in frames],
        default_frame_reference_color=color,
    )


@pytest.fixture
def color_env(monkeypatch, tmp_path):
    """Color files go to a temp dir."""
    monkeypatch.setattr("services.frame_reference_color.FRAME_COLOR_DIR", str(tmp_path))
    return tmp_path


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "frames, message_key",
    [
        ([], "frame_reference_color_requires_one_frame"),
        (["first_frame", "last_frame"], "no_free_frame_slot"),
    ],
)
async def test_frame_color_rejected_when_user_frames_are_not_exactly_one(
    authed_client,
    project_task,
    generation_menu_feature,
    two_frame_video_model,
    fake_generation_backends,
    color_env,
    frames,
    message_key,
):
    """422; the color needs exactly one user-supplied frame (it fills the other). Nothing is written or dispatched."""
    menu, feature = generation_menu_feature
    body = _color_payload(menu, feature, two_frame_video_model, frames)
    resp = await authed_client.call("POST", _url(project_task.uid), json=body, raise_for_status=False)
    assert resp.status_code == 422
    assert resp.json()["message"] == resolve_message(message_key, "en")
    assert fake_generation_backends == []
    assert list(color_env.iterdir()) == []


@pytest.mark.asyncio
async def test_frame_color_rejected_on_single_frame_model(
    authed_client,
    project_task,
    generation_menu_feature,
    video_model,
    pic_api_key,
    generation_project_settings,
    fake_generation_backends,
    color_env,
):
    """422; a model with only first_frame can't take the color."""
    menu, feature = generation_menu_feature
    body = _color_payload(menu, feature, video_model, ["first_frame"])
    resp = await authed_client.call("POST", _url(project_task.uid), json=body, raise_for_status=False)
    assert resp.status_code == 422
    assert resp.json()["message"] == resolve_message("frame_reference_color_requires_two_frames", "en")
    assert fake_generation_backends == []


@pytest.mark.asyncio
async def test_frame_color_fills_the_missing_frame_and_is_saved(
    authed_client,
    project_task,
    generation_menu_feature,
    two_frame_video_model,
    pic_api_key,
    generation_project_settings,
    fake_generation_backends,
    color_env,
    db_session,
):
    """200; with first_frame sent, the color becomes last_frame in the dispatched payload, the image file
    exists, and the color is stored on the generation row."""
    menu, feature = generation_menu_feature
    payload = _color_payload(menu, feature, two_frame_video_model, ["first_frame"])
    resp = await authed_client.call("POST", _url(project_task.uid), json=payload)
    assert resp.status_code == 200
    assert len(fake_generation_backends) == 1

    sent = fake_generation_backends[0][1]["payload"]
    assert [f["frame_type"] for f in sent["frame_images"]] == ["first_frame", "last_frame"]
    assert sent["frame_images"][1]["image_url"]["url"].endswith("/%234cfb2b_16%3A9.jpg")
    assert (color_env / "#4cfb2b_16:9.jpg").exists()

    assert (await _latest_generation(db_session, project_task.id)).color_code == "#4cfb2b"


@pytest.mark.asyncio
async def test_prompt_is_dispatched_with_the_feature_prompts_after_the_guardrail(
    authed_client,
    project_task,
    generation_menu_feature,
    image_model,
    pic_api_key,
    generation_project_settings,
    fake_generation_backends,
    guardrail,
    db_session,
):
    """200 OK; the passed prompt is checked once, then saved and dispatched.
    Row: raw_prompt = schema.prompt, full_prompt = prompt + templates, finalized_prompt = full_prompt."""
    menu, feature = generation_menu_feature
    resp = await authed_client.call("POST", _url(project_task.uid), json=_payload(menu, feature, image_model))
    assert resp.status_code == 200
    assert len(guardrail.calls) == 1

    row = await _latest_generation(db_session, project_task.id)
    assert row.raw_prompt == "a scenic mountain view at sunrise"
    assert row.full_prompt.startswith(row.raw_prompt)
    assert row.finalized_prompt == row.full_prompt
    assert fake_generation_backends[-1][1]["payload"]["prompt"] == row.full_prompt
