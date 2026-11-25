import json
import pytest
from uuid import uuid4
from middlewares.lang import resolve_message
from sqlalchemy import select
from services.mysql.model import DfEngineModelOptions, DfEngineSettings, DfEngineSettingLogs
from services.mysql.factory.df_engine_model_options import DfEngineModelOptionsFactory
from services.redis import client as redis_client, CacheKeys
from tests.helpers import available_model_rows, openrouter_item_from_row, clear_setting_state

URL = "/api/models"
TEXT_PATH = "/models?output_modalities=text"


async def _available_text_rows(db_session) -> list[DfEngineModelOptions]:
    return await available_model_rows(db_session, "text")


_item_from_row = openrouter_item_from_row


@pytest.mark.asyncio
async def test_sync_skips_unconfigured_types_without_side_effects(authed_client, db_session, mock_model_sync):
    """200 OK; with nothing configured on `mock_model_sync`, every type gets a
    5xx response and is skipped — real rows are provably untouched."""
    before = {
        t: (
            await db_session.execute(
                select(DfEngineModelOptions.is_available).where(DfEngineModelOptions.type == t)  # type: ignore
            )
        )
        .scalars()
        .all()
        for t in ("text", "image", "video")
    }

    resp = await authed_client.call("POST", URL)
    assert resp.status_code == 200

    await db_session.rollback()
    after = {
        t: (
            await db_session.execute(
                select(DfEngineModelOptions.is_available).where(DfEngineModelOptions.type == t)  # type: ignore
            )
        )
        .scalars()
        .all()
        for t in ("text", "image", "video")
    }
    for usage_type in ("text", "image", "video"):
        assert sorted(before[usage_type]) == sorted(after[usage_type])


@pytest.mark.asyncio
async def test_sync_inserts_new_model_and_preserves_existing_catalog(authed_client, db_session, mock_model_sync):
    """200 OK; syncing `text` with its full real catalog plus one new item
    inserts only the new item and disables nothing already on file."""
    existing_rows = await _available_text_rows(db_session)
    new_model_id = f"test-vendor/http-insert-{uuid4().hex[:10]}"
    items = [_item_from_row(row) for row in existing_rows] + [{"id": new_model_id, "name": "HTTP Insert Test"}]
    mock_model_sync.set(TEXT_PATH, items)

    resp = await authed_client.call("POST", URL)
    assert resp.status_code == 200

    await db_session.rollback()
    inserted = (
        await db_session.execute(
            select(DfEngineModelOptions).where(
                DfEngineModelOptions.model_id == new_model_id,  # type: ignore
                DfEngineModelOptions.type == "text",  # type: ignore
            )
        )
    ).scalar_one()
    assert inserted.is_available is True

    still_available = await _available_text_rows(db_session)
    assert len(existing_rows) + 1 == len(still_available)


@pytest.mark.asyncio
async def test_sync_refreshes_present_model_and_flags_missing_one_unavailable(
    authed_client, db_session, mock_model_sync
):
    """200 OK; a model still in the response is refreshed and stays available; one
    absent from it is flagged is_available=False. Both are brand-new,
    uniquely-named factory rows so no real catalog data is touched."""
    kept = DfEngineModelOptionsFactory.create(type="text", is_available=True, is_enabled=False, is_main=False)
    dropped = DfEngineModelOptionsFactory.create(type="text", is_available=True, is_enabled=False, is_main=False)

    rows = await _available_text_rows(db_session)
    items = [
        {**_item_from_row(r), "name": "Kept Renamed"} if r.model_id == kept.model_id else _item_from_row(r)
        for r in rows
        if r.model_id != dropped.model_id
    ]
    mock_model_sync.set(TEXT_PATH, items)

    resp = await authed_client.call("POST", URL)
    assert resp.status_code == 200

    await db_session.rollback()
    kept_after = (
        await db_session.execute(
            select(DfEngineModelOptions).where(DfEngineModelOptions.id == kept.id)  # type: ignore
        )
    ).scalar_one()
    dropped_after = (
        await db_session.execute(
            select(DfEngineModelOptions).where(DfEngineModelOptions.id == dropped.id)  # type: ignore
        )
    ).scalar_one()
    assert kept_after.is_available is True
    assert kept_after.name == "Kept Renamed"
    assert dropped_after.is_available is False


@pytest.mark.asyncio
async def test_sync_refreshes_a_soft_deleted_model_but_keeps_it_deleted(authed_client, db_session, mock_model_sync):
    """200 OK; a soft-deleted model OpenRouter still lists gets fresh metadata and stays deleted."""
    from utils import local_time

    deleted = DfEngineModelOptionsFactory.create(
        type="text", is_available=False, is_enabled=False, is_main=False, deleted_at=local_time(), deleted_by=1
    )
    rows = await _available_text_rows(db_session)
    mock_model_sync.set(TEXT_PATH, [_item_from_row(r) for r in rows] + [{"id": deleted.model_id, "name": "Refreshed"}])

    resp = await authed_client.call("POST", URL)
    assert resp.status_code == 200

    await db_session.rollback()
    after = (
        await db_session.execute(select(DfEngineModelOptions).where(DfEngineModelOptions.id == deleted.id))
    ).scalar_one()
    assert (after.name, after.is_available, after.uid) == ("Refreshed", True, deleted.uid)
    assert after.deleted_at is not None
    assert after.deleted_by == 1


@pytest.mark.asyncio
async def test_sync_flags_a_soft_deleted_model_unavailable_when_gone_from_openrouter(
    authed_client, db_session, mock_model_sync
):
    """200 OK; a soft-deleted model absent from the response is flagged unavailable and stays deleted."""
    from utils import local_time

    deleted = DfEngineModelOptionsFactory.create(
        type="text", is_available=True, is_enabled=False, is_main=False, deleted_at=local_time(), deleted_by=1
    )
    rows = await _available_text_rows(db_session)
    mock_model_sync.set(TEXT_PATH, [_item_from_row(r) for r in rows if r.model_id != deleted.model_id])

    resp = await authed_client.call("POST", URL)
    assert resp.status_code == 200

    await db_session.rollback()
    after = (
        await db_session.execute(select(DfEngineModelOptions).where(DfEngineModelOptions.id == deleted.id))
    ).scalar_one()
    assert after.is_available is False
    assert after.deleted_at is not None


@pytest.mark.asyncio
async def test_sync_keeps_enabled_and_main_flags(authed_client, db_session, mock_model_sync):
    """200 OK; sync never changes `is_enabled` / `is_main`, whether the model is still listed or not."""
    listed = DfEngineModelOptionsFactory.create(type="text", is_available=True, is_enabled=True, is_main=True)
    dropped = DfEngineModelOptionsFactory.create(type="text", is_available=True, is_enabled=True, is_main=False)
    rows = await _available_text_rows(db_session)
    mock_model_sync.set(TEXT_PATH, [_item_from_row(r) for r in rows if r.model_id != dropped.model_id])

    await authed_client.call("POST", URL)

    await db_session.rollback()
    after = {
        r.id: r
        for r in (
            await db_session.execute(
                select(DfEngineModelOptions).where(DfEngineModelOptions.id.in_([listed.id, dropped.id]))  # type: ignore
            )
        ).scalars()
    }
    assert (after[listed.id].is_enabled, after[listed.id].is_main, after[listed.id].is_available) == (True, True, True)
    assert (after[dropped.id].is_enabled, after[dropped.id].is_available) == (True, False)


@pytest.mark.asyncio
async def test_sync_skips_a_type_with_an_empty_model_list(authed_client, db_session, mock_model_sync):
    """200 OK; an empty list is treated as a bad response, so nothing is flagged unavailable."""
    row = DfEngineModelOptionsFactory.create(type="text", is_available=True, is_enabled=False, is_main=False)
    mock_model_sync.set(TEXT_PATH, [])

    resp = await authed_client.call("POST", URL)
    assert resp.status_code == 200

    await db_session.rollback()
    assert (
        await db_session.execute(select(DfEngineModelOptions.is_available).where(DfEngineModelOptions.id == row.id))
    ).scalar_one() is True


@pytest.mark.asyncio
async def test_sync_is_limited_to_once_a_minute(authed_client, mock_model_sync):
    """429 with a readable message on a second sync inside the same minute."""
    assert (await authed_client.call("POST", URL)).status_code == 200

    resp = await authed_client.call("POST", URL, raise_for_status=False)
    assert resp.status_code == 429
    assert resp.json()["message"] == resolve_message("model_sync_rate_limit_exceeded", "en").format(times=1, seconds=60)


@pytest.mark.asyncio
async def test_sync_ignores_items_without_an_id(authed_client, db_session, mock_model_sync):
    """200 OK; an item missing `id` is skipped, not inserted; valid items alongside it
    still sync."""
    rows = await _available_text_rows(db_session)
    valid_id = f"test-vendor/with-id-{uuid4().hex[:10]}"
    items = [_item_from_row(r) for r in rows] + [{"name": "no id here"}, {"id": valid_id, "name": "Has An Id"}]
    mock_model_sync.set(TEXT_PATH, items)

    resp = await authed_client.call("POST", URL)
    assert resp.status_code == 200

    await db_session.rollback()
    assert (
        await db_session.execute(
            select(DfEngineModelOptions).where(DfEngineModelOptions.model_id == valid_id)  # type: ignore
        )
    ).scalar_one().is_available is True
    assert (
        await db_session.execute(
            select(DfEngineModelOptions.id).where(DfEngineModelOptions.name == "no id here")  # type: ignore
        )
    ).scalars().all() == []


@pytest.mark.asyncio
async def test_sync_nulls_engine_setting_when_main_model_goes_unavailable(authed_client, db_session, mock_model_sync):
    """200 OK; a main text model that sync makes unavailable is dropped from any
    `admin_setting` still pointing at it (enhancer_model / assistant_model),
    and the change is written to df_engine_setting_logs."""
    await clear_setting_state(db_session)
    main_model = DfEngineModelOptionsFactory.create(type="text", is_available=True, is_enabled=True, is_main=True)
    model_ref = {"uid": main_model.uid, "name": main_model.name}
    db_session.add_all(
        DfEngineSettings(code="admin_setting", key=key, value=json.dumps(model_ref))
        for key in ("enhancer_model", "assistant_model")
    )
    await db_session.commit()

    rows = await _available_text_rows(db_session)
    items = [_item_from_row(r) for r in rows if r.model_id != main_model.model_id]
    mock_model_sync.set(TEXT_PATH, items)

    resp = await authed_client.call("POST", URL)
    assert resp.status_code == 200

    await db_session.rollback()
    settings = (
        (
            await db_session.execute(
                select(DfEngineSettings).where(
                    DfEngineSettings.code == "admin_setting",  # type: ignore
                    DfEngineSettings.key.in_(("enhancer_model", "assistant_model")),  # type: ignore
                )
            )
        )
        .scalars()
        .all()
    )
    assert {s.value for s in settings} == {json.dumps(None)}

    logs = (await db_session.execute(select(DfEngineSettingLogs))).scalars().all()
    assert len(logs) == 1
    assert logs[0].previous_data == {
        "enhancer_model": model_ref,
        "assistant_model": model_ref,
    }
    assert logs[0].incoming_data == {
        "enhancer_model": None,
        "assistant_model": None,
    }

    model_after = (
        await db_session.execute(
            select(DfEngineModelOptions).where(DfEngineModelOptions.id == main_model.id)  # type: ignore
        )
    ).scalar_one()
    assert model_after.is_available is False


@pytest.mark.asyncio
async def test_sync_nulls_only_the_setting_whose_model_is_unavailable(authed_client, db_session, mock_model_sync):
    """200 OK; a non-main model counts too, a legacy name-only value is understood,
    and the setting that still points at an available model is kept."""
    await clear_setting_state(db_session)
    kept = DfEngineModelOptionsFactory.create(type="text", is_available=True, is_enabled=True, is_main=False)
    gone = DfEngineModelOptionsFactory.create(
        name=f"Gone{uuid4().hex[:8]}", type="text", is_available=True, is_enabled=True, is_main=False
    )
    kept_ref = {"uid": kept.uid, "name": kept.name}
    db_session.add_all(
        [
            DfEngineSettings(code="admin_setting", key="enhancer_model", value=json.dumps(kept_ref)),
            DfEngineSettings(code="admin_setting", key="assistant_model", value=json.dumps(gone.name)),
        ]
    )
    await db_session.commit()
    rows = await _available_text_rows(db_session)
    mock_model_sync.set(TEXT_PATH, [_item_from_row(r) for r in rows if r.model_id != gone.model_id])

    await authed_client.call("POST", URL)

    await db_session.rollback()
    values = dict(
        (
            await db_session.execute(
                select(DfEngineSettings.key, DfEngineSettings.value).where(DfEngineSettings.code == "admin_setting")  # type: ignore
            )
        ).all()
    )
    assert json.loads(values["enhancer_model"]) == kept_ref
    assert json.loads(values["assistant_model"]) is None
    log = (await db_session.execute(select(DfEngineSettingLogs))).scalar_one()
    assert log.incoming_data == {"enhancer_model": kept_ref, "assistant_model": None}
    await clear_setting_state(db_session)


@pytest.mark.asyncio
async def test_sync_leaves_valid_and_empty_settings_alone(authed_client, db_session, mock_model_sync):
    """200 OK; nothing dangling means no setting change and no log entry."""
    await clear_setting_state(db_session)
    kept = DfEngineModelOptionsFactory.create(type="text", is_available=True, is_enabled=True, is_main=False)
    db_session.add_all(
        [
            DfEngineSettings(code="admin_setting", key="enhancer_model", value=json.dumps({"uid": kept.uid})),
            DfEngineSettings(code="admin_setting", key="assistant_model", value=json.dumps(None)),
        ]
    )
    await db_session.commit()
    rows = await _available_text_rows(db_session)
    mock_model_sync.set(TEXT_PATH, [_item_from_row(r) for r in rows])

    await authed_client.call("POST", URL)

    await db_session.rollback()
    assert (await db_session.execute(select(DfEngineSettingLogs))).scalars().all() == []
    await clear_setting_state(db_session)


@pytest.mark.asyncio
async def test_sync_invalidates_the_list_cache(authed_client, db_session, mock_model_sync):
    """200 OK; syncing a type clears every cached list page."""
    redis = redis_client()
    rows = await _available_text_rows(db_session)
    mock_model_sync.set(TEXT_PATH, [_item_from_row(r) for r in rows])
    await authed_client.call("GET", URL)
    key = CacheKeys().model_pagination_refactored(page=1, itemsPerPage=500)
    assert await redis.exists(key)

    resp = await authed_client.call("POST", URL)
    assert resp.status_code == 200
    assert not await redis.exists(key)


@pytest.mark.asyncio
async def test_requires_auth(client):
    """401 when the request carries no bearer token."""
    resp = await client.call("POST", URL, raise_for_status=False)
    assert resp.status_code == 401
