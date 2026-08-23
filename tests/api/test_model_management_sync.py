"""Tests for POST /models (sync).

`sync_model_type` reconciles a WHOLE usage type against OpenRouter's response:
anything of that type not in the response gets flagged `is_available = False`.
`df_engine_model_options` is real, shared, already-synced data (hundreds of rows
per type) — so a naive test that hits the real HTTP endpoint with a small,
incomplete fake model list would mass-disable every real row of that type.

To stay safe:
  - `mock_model_sync` (see conftest.py) fails an unconfigured type safe — it
    returns an error-shaped payload, which the controller treats as "skip this
    type", not "OpenRouter returned zero models".
  - The one true HTTP round-trip test below only ever configures a type with
    its OWN full current catalog (reconstructed from the DB) plus one new
    item, so nothing pre-existing can be disabled.
  - Scenarios that legitimately need to omit/replace existing rows (disable,
    skipped-item counting) call `sync_model_type` directly against `db_session`
    inside a SAVEPOINT (`db_session.begin_nested()`) that's always rolled back,
    so the mass-effect never reaches the real table even transiently past this
    test process.
"""

import pytest
from typing import Any
from uuid import uuid4
from sqlalchemy import select
from services.mysql.model import DfEngineModelOptions
from tests.helpers import create_record
from apps.controller.model_management import ModelManagementController

URL = "/api/models"


def _model_option_data(**overrides: Any) -> dict[str, Any]:
    unique = uuid4().hex[:10]
    data = dict(
        uid=str(uuid4()),
        model_id=f"test-vendor/test-model-{unique}",
        name=f"SyncTest-{unique}",
        type="text",
        is_available=True,
        is_enabled=False,
        is_main=False,
    )
    data.update(overrides)
    return data


def _item_from_row(row: DfEngineModelOptions) -> dict[str, Any]:
    """Reconstruct an OpenRouter-shaped item from a stored row — the exact
    reverse of `ModelManagementController.model_option_fields`. Used so a
    fake sync response can safely include the FULL real catalog for a type
    (each real row round-trips to its own current values) alongside new
    test items, without wiping or disabling anything real.
    """
    return {
        "id": row.model_id,
        "name": row.name,
        "created": row.created,
        "description": row.description,
        "architecture": row.architecture,
        "supported_parameters": row.supported_parameters,
        "default_parameters": row.default_parameters,
        "supports_streaming": row.supports_streaming,
        "supported_resolutions": row.supported_resolutions,
        "supported_aspect_ratios": row.supported_aspect_ratios,
        "supported_sizes": row.supported_sizes,
        "supported_durations": row.supported_durations,
        "supported_frame_images": row.supported_frame_images,
        "generate_audio": row.generate_audio,
        "allowed_passthrough_parameters": row.allowed_passthrough_parameters,
        "pricing_skus": row.pricing_skus,
        "pricing": row.pricing,
        "top_provider": row.top_provider,
        "knowledge_cutoff": row.knowledge_cutoff.isoformat() if row.knowledge_cutoff else None,
        "expiration_date": row.expiration_date.isoformat() if row.expiration_date else None,
    }


def _controller(db_session, user_id: str) -> ModelManagementController:
    ctrl = ModelManagementController.__new__(ModelManagementController)
    ctrl.db = db_session
    ctrl.user = {"user_id": int(user_id)}
    return ctrl


@pytest.mark.asyncio
async def test_sync_http_skips_unconfigured_types_without_side_effects(authed_client, db_session, mock_model_sync):
    """200 OK; with nothing configured on `mock_model_sync`, every type gets an
    error-shaped response and is skipped — real rows are provably untouched."""
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

    await db_session.rollback()  # see the endpoint's own committed writes (or lack thereof)
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
    """200 OK; syncing a type with its full real catalog plus one new item inserts
    only the new item and disables nothing already on file."""
    # Only currently-available rows — a real OpenRouter response would only ever
    # echo back models it still has, never ones already flagged unavailable
    # locally, so reconstructing from the full row set (including disabled ones)
    # would incorrectly "resurrect" them.
    existing_rows = (
        (
            await db_session.execute(
                select(DfEngineModelOptions).where(
                    DfEngineModelOptions.type == "text",  # type: ignore
                    DfEngineModelOptions.is_available.is_(True),  # type: ignore
                )
            )
        )
        .scalars()
        .all()
    )
    new_model_id = f"test-vendor/http-insert-{uuid4().hex[:10]}"
    items = [_item_from_row(row) for row in existing_rows] + [{"id": new_model_id, "name": "HTTP Insert Test"}]
    mock_model_sync.set("/models?output_modalities=text", items)

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

    still_available = (
        await db_session.execute(
            select(DfEngineModelOptions.id).where(  # type: ignore
                DfEngineModelOptions.type == "text",  # type: ignore
                DfEngineModelOptions.is_available.is_(True),  # type: ignore
            )
        )
    ).scalars()
    assert len(existing_rows) + 1 == len(list(still_available))


@pytest.mark.asyncio
async def test_sync_flags_missing_model_unavailable(db_session, user_id):
    """A model previously on file but absent from the latest OpenRouter response
    gets flagged is_available=False; one still present gets refreshed and stays
    available. `kept`/`dropped` are created and committed normally first (safe —
    brand-new, uniquely-named rows); only the sync call itself runs inside a
    SAVEPOINT (never committed), since sync_model_type also mass-disables every
    other real row of the type as a side effect. `create_record` calls
    `.commit()` internally, which can't happen inside `begin_nested()`."""
    kept = await create_record(db_session, DfEngineModelOptions, _model_option_data(is_available=True))
    dropped = await create_record(db_session, DfEngineModelOptions, _model_option_data(is_available=True))

    async with db_session.begin_nested():
        ctrl = _controller(db_session, user_id)
        result = await ctrl.sync_model_type("text", [{"id": kept.model_id, "name": "Kept Renamed"}])
        await db_session.flush()

        assert result["updated"] >= 1
        assert result["disabled"] >= 1

        await db_session.refresh(kept)
        await db_session.refresh(dropped)
        assert kept.is_available is True
        assert kept.name == "Kept Renamed"
        assert dropped.is_available is False

        await db_session.rollback()


@pytest.mark.asyncio
async def test_sync_skips_items_missing_id(db_session, user_id):
    """Items without an `id` are counted as skipped, not inserted. Run inside a
    SAVEPOINT for the same reason as the disable test above."""
    async with db_session.begin_nested():
        ctrl = _controller(db_session, user_id)
        result = await ctrl.sync_model_type("text", [{"id": None}, {"name": "no id here"}])

        assert result["inserted"] == 0
        assert result["skipped"] == 2

        await db_session.rollback()


@pytest.mark.asyncio
async def test_requires_auth(client):
    """401 when the request carries no bearer token."""
    resp = await client.call("POST", URL, raise_for_status=False)
    assert resp.status_code == 401
