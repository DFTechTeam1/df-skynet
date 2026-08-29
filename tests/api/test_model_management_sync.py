"""Tests for POST /models (sync).

The sync endpoint reconciles a WHOLE usage type against OpenRouter's response:
anything of that type not in the response gets flagged `is_available = False`.
`df_engine_model_options` is real, shared, already-synced data (hundreds of rows
per type) — so a naive test that configures a small, incomplete fake model list
would mass-disable every real row of that type.

To stay safe every test here that goes through the HTTP endpoint configures the
`text` path with its OWN full current catalog (reconstructed from the DB) and
then adds / omits exactly the one row it wants to exercise, so nothing else can
be inserted or disabled as a side effect. Unconfigured paths (`video`, `image`)
return a 5xx from the mock and are skipped untouched.
"""

import json
import pytest
from uuid import uuid4
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
    """A model still in the response is refreshed and stays available; one
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
async def test_sync_ignores_items_without_an_id(authed_client, db_session, mock_model_sync):
    """An item missing `id` is skipped, not inserted; valid items alongside it
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
    """A main text model that sync makes unavailable is dropped from any
    `admin_setting` still pointing at it (enhancer_model / assistant_model),
    and the change is written to df_engine_setting_logs."""
    await clear_setting_state(db_session)
    main_model = DfEngineModelOptionsFactory.create(type="text", is_available=True, is_enabled=True, is_main=True)
    db_session.add_all(
        DfEngineSettings(code="admin_setting", key=key, value=json.dumps(main_model.name))
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
        "enhancer_model": json.dumps(main_model.name),
        "assistant_model": json.dumps(main_model.name),
    }
    assert logs[0].incoming_data == {
        "enhancer_model": json.dumps(None),
        "assistant_model": json.dumps(None),
    }

    model_after = (
        await db_session.execute(
            select(DfEngineModelOptions).where(DfEngineModelOptions.id == main_model.id)  # type: ignore
        )
    ).scalar_one()
    assert model_after.is_available is False


@pytest.mark.asyncio
async def test_sync_invalidates_the_list_cache(authed_client, mock_model_sync):
    """200 OK; even a no-op sync still clears every cached list page — sync
    always ends by flushing the model-option cache namespace."""
    redis = redis_client()
    await authed_client.call("GET", URL)
    key = CacheKeys().model_pagination(1, 500, None, None, None)
    assert await redis.exists(key)

    resp = await authed_client.call("POST", URL)
    assert resp.status_code == 200
    assert not await redis.exists(key)


@pytest.mark.asyncio
async def test_requires_auth(client):
    """401 when the request carries no bearer token."""
    resp = await client.call("POST", URL, raise_for_status=False)
    assert resp.status_code == 401
