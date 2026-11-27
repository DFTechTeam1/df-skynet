import pytest
from middlewares.lang import resolve_message
from services.mysql.model.entertainment_task_songs import SONG_STATUS_ON_PROGRESS
from services.repository.projects import ProjectRepository
from tests.generation_fixtures import (  # noqa: F401  (fixtures)
    fake_generation_backends,
    generation_menu_feature,
    generation_project_settings,
    guardrail,
    image_model,
    make_song,
    override_repo,
    payload as _payload,
    pic_api_key,
    pic_employee_id,
    project_lead,
)

URL = "/api/generations"
TASK_COMPLETED, TASK_NOT_ONGOING = 4, 2


@pytest.fixture
def generate(
    authed_client,
    project_task,
    generation_menu_feature,
    image_model,
    pic_api_key,
    generation_project_settings,
    fake_generation_backends,
):
    """`await generate(task_uid=None)` sends a request that passes every check unless a test breaks one."""
    menu, feature = generation_menu_feature

    async def _generate(task_uid=None):
        body = _payload(menu, feature, image_model)
        return await authed_client.call(
            "POST", f"{URL}/{task_uid or project_task.uid}", json=body, raise_for_status=False
        )

    return _generate


def _task_change(**changes):
    # `get_task` first asks the same method for just the id, which isn't a record, so it stays untouched
    return lambda record: record.update(changes)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "status, key",
    [(TASK_COMPLETED, "project_task_already_completed"), (TASK_NOT_ONGOING, "project_task_not_ongoing")],
)
async def test_task_that_is_not_ongoing_is_refused(generate, override_repo, fake_generation_backends, status, key):
    override_repo(ProjectRepository, "get_production_task", _task_change(status=status))
    resp = await generate()
    assert resp.status_code == 422
    assert resp.json()["message"] == resolve_message(key, "en")
    assert fake_generation_backends == []


@pytest.mark.asyncio
async def test_project_not_ongoing_is_refused(generate, override_repo, fake_generation_backends):
    override_repo(ProjectRepository, "get_project", lambda record: record.update(status=2))
    resp = await generate()
    assert resp.status_code == 422
    assert resp.json()["message"] == resolve_message("project_not_ongoing", "en")
    assert fake_generation_backends == []


@pytest.mark.asyncio
async def test_unassigned_non_override_user_is_refused(generate, override_repo, as_roles, fake_generation_backends):
    as_roles(["staff"])
    override_repo(ProjectRepository, "get_production_task", _task_change(project_task_pics=[]))
    resp = await generate()
    assert resp.status_code == 404
    assert resp.json()["message"] == resolve_message("employee_not_assigned_task", "en")
    assert fake_generation_backends == []


@pytest.mark.asyncio
async def test_non_override_user_on_someone_elses_song_is_refused(
    generate, make_song, pic_employee_id, as_roles, fake_generation_backends
):
    as_roles(["staff"])
    song = await make_song(SONG_STATUS_ON_PROGRESS, employee_id=pic_employee_id)
    resp = await generate(song.uid)
    assert resp.status_code == 404
    assert resp.json()["message"] == resolve_message("employee_not_assigned_task", "en")
    assert fake_generation_backends == []


@pytest.mark.asyncio
async def test_override_role_skips_the_assignment_check(generate, as_roles, fake_generation_backends):
    as_roles(["director"])
    resp = await generate()
    assert resp.status_code == 200, resp.text
    assert len(fake_generation_backends) == 1


@pytest.mark.asyncio
async def test_unknown_task_is_404(generate):
    resp = await generate("11111111-1111-1111-1111-111111111111")
    assert resp.status_code == 404
    assert resp.json()["message"] == resolve_message("project_task_not_found", "en")


@pytest.mark.asyncio
async def test_invalid_frame_reference_color_returns_readable_message(authed_client):
    """A bad hex is a 422 whose headline is the translated sentence, not 'Malformed JSON.'"""
    payload = {"prompt": "a mountain", "type": "video", "parameter": {"aspect_ratio": "21:9"}}
    resp = await authed_client.call(
        "POST",
        f"{URL}/11111111-1111-1111-1111-111111111111",
        json={**payload, "default_frame_reference_color": "tes"},
        raise_for_status=False,
    )
    assert resp.status_code == 422
    body = resp.json()
    expected = resolve_message("default_frame_reference_color_invalid_format", "en")
    assert body["message"] == expected != "default_frame_reference_color_invalid_format"
    assert body["error"]["default_frame_reference_color"] == [expected]


@pytest.mark.asyncio
async def test_frame_reference_color_on_image_generation_is_422(authed_client):
    resp = await authed_client.call(
        "POST",
        f"{URL}/11111111-1111-1111-1111-111111111111",
        json={"prompt": "a mountain", "type": "image", "parameter": {}, "default_frame_reference_color": "#fb542b"},
        raise_for_status=False,
    )
    assert resp.status_code == 422
    assert resp.json()["message"] == resolve_message("default_frame_reference_color_requires_video_type", "en")
