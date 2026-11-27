import pytest
from sqlalchemy import select
from middlewares.lang import resolve_message
from services.mysql.model import DfEngineGenerations
from services.mysql.model.entertainment_task_songs import SONG_STATUS_ON_PROGRESS, SONG_STATUS_COMPLETED
from tests.generation_fixtures import (  # noqa: F401  (fixtures)
    fake_generation_backends,
    generation_menu_feature,
    generation_project_settings,
    guardrail,
    image_model,
    make_song,
    payload as _payload,
    pic_api_key,
    pic_employee_id,
    project_lead,
)

URL = "/api/generations"


@pytest.mark.asyncio
async def test_generating_against_a_song_task_sets_song_id_not_task_id(
    authed_client,
    make_song,
    generation_menu_feature,
    image_model,
    pic_api_key,
    generation_project_settings,
    fake_generation_backends,
    db_session,
):
    song = await make_song(SONG_STATUS_ON_PROGRESS)
    menu, feature = generation_menu_feature
    resp = await authed_client.call("POST", f"{URL}/{song.uid}", json=_payload(menu, feature, image_model))
    assert resp.status_code == 200
    assert len(fake_generation_backends) == 1

    generation_uid = resp.json()["data"]["generation_uid"]
    row = (
        (await db_session.execute(select(DfEngineGenerations).where(DfEngineGenerations.uid == generation_uid)))
        .scalars()
        .first()
    )
    assert row.song_id == song.id
    assert row.task_id is None


@pytest.mark.asyncio
async def test_generating_against_a_completed_song_task_is_refused(
    authed_client,
    make_song,
    generation_menu_feature,
    image_model,
    pic_api_key,
    generation_project_settings,
    fake_generation_backends,
):
    """422 song_task_already_completed; a completed song can no longer be generated against."""
    song = await make_song(SONG_STATUS_COMPLETED)
    menu, feature = generation_menu_feature
    resp = await authed_client.call(
        "POST", f"{URL}/{song.uid}", json=_payload(menu, feature, image_model), raise_for_status=False
    )
    assert resp.status_code == 422
    assert resp.json()["message"] == resolve_message("song_task_already_completed", "en")
    assert fake_generation_backends == []
