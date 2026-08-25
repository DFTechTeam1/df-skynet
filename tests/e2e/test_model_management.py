"""End-to-end journeys for model management: fetch, enable/disable, and
set-main chained together. Deliberately never calls POST /models (sync) —
that endpoint reconciles a WHOLE usage type against OpenRouter and would
mass-disable real, already-synced rows if driven by a small fake response
(see tests/api/test_model_management_sync.py for how that's tested safely
instead). Journeys here start from rows created directly via `create_record`,
standing in for "already synced" models, and only ever act on them by uid.
"""

import pytest
import pytest_asyncio
from typing import Any
from uuid import uuid4
from sqlalchemy import select
from services.mysql.model import DfEngineModelOptions
from tests.helpers import create_record

URL = "/api/models"


@pytest_asyncio.fixture(autouse=True)
async def _restore_real_main_state(db_session):
    """These journeys promote fixtures to main alongside any REAL,
    already-synced row. Snapshot every row that's main before the test and
    force that exact set back afterward — see the identical fixture in
    tests/api/test_model_management_set_main.py for the full rationale.
    """
    before_ids = set(
        (await db_session.execute(select(DfEngineModelOptions.id).where(DfEngineModelOptions.is_main.is_(True))))
        .scalars()
        .all()
    )
    yield
    await db_session.rollback()
    current = (
        (await db_session.execute(select(DfEngineModelOptions).where(DfEngineModelOptions.is_main.is_(True))))
        .scalars()
        .all()
    )
    for row in current:
        if row.id not in before_ids:
            row.is_main = False
    for row_id in before_ids:
        row = await db_session.get(DfEngineModelOptions, row_id)
        if row is not None and not row.is_main:
            row.is_main = True
    await db_session.commit()


def _model_option_data(**overrides: Any) -> dict[str, Any]:
    unique = uuid4().hex[:10]
    data = dict(
        uid=str(uuid4()),
        model_id=f"test-vendor/test-model-{unique}",
        name=f"E2E-{unique}",
        type="text",
        is_available=True,
        is_enabled=False,
        is_main=False,
    )
    data.update(overrides)
    return data


async def _fetch_item(authed_client, search: str) -> dict[str, Any]:
    resp = await authed_client.call("GET", URL, params={"search": search})
    items = resp.json()["data"]["paginated"]
    assert len(items) == 1, f"expected exactly one match for search={search!r}, got {items}"
    return items[0]


@pytest.mark.asyncio
async def test_enable_promote_then_second_main_journey(authed_client, db_session):
    """A synced-but-idle model gets enabled, promoted to main, then a second
    candidate is promoted too — a type can have more than one main model,
    so the first stays main."""
    prefix = f"Journey{uuid4().hex[:8]}"
    model_a = await create_record(
        db_session, DfEngineModelOptions, _model_option_data(name=f"{prefix}-a", type="video")
    )

    # 1. freshly synced: visible, disabled, not eligible for main yet
    item = await _fetch_item(authed_client, model_a.name)
    assert item["is_enabled"] is False
    assert item["action"] == {"can_set_enabled": True, "can_set_main": False}

    # 2. enable it
    enable_resp = await authed_client.call("PATCH", f"{URL}/{model_a.uid}", json={"is_enabled": True})
    assert enable_resp.status_code == 200
    assert enable_resp.json()["data"]["is_enabled"] is True

    # 3. now eligible, promote to main
    main_resp = await authed_client.call("PATCH", f"{URL}/{model_a.uid}/main")
    assert main_resp.status_code == 200
    assert main_resp.json()["data"]["is_main"] is True

    item = await _fetch_item(authed_client, model_a.name)
    assert item["is_main"] is True

    # 4. a second, same-type candidate shows up and gets enabled
    model_b = await create_record(
        db_session, DfEngineModelOptions, _model_option_data(name=f"{prefix}-b", type="video")
    )
    await authed_client.call("PATCH", f"{URL}/{model_b.uid}", json={"is_enabled": True})

    # 5. promoting B leaves A as main too — a type can have more than one main
    second_resp = await authed_client.call("PATCH", f"{URL}/{model_b.uid}/main")
    assert second_resp.status_code == 200
    assert second_resp.json()["data"]["is_main"] is True

    item_a = await _fetch_item(authed_client, model_a.name)
    item_b = await _fetch_item(authed_client, model_b.name)
    assert item_a["is_main"] is True
    assert item_b["is_main"] is True


@pytest.mark.asyncio
async def test_disable_cascades_then_unavailable_blocks_actions_journey(authed_client, db_session):
    """Disabling a main model cascades to clear is_main; once the model is
    later flagged unavailable (as sync would do), it disappears from the
    fetch list and both enable/disable and set-main are rejected."""
    row = await create_record(
        db_session,
        DfEngineModelOptions,
        _model_option_data(type="image", is_enabled=True, is_main=True),
    )

    # 1. confirmed live: enabled and main
    item = await _fetch_item(authed_client, row.name)
    assert item["is_enabled"] is True
    assert item["is_main"] is True

    # 2. disable it — cascades to clear is_main in the same call
    disable_resp = await authed_client.call("PATCH", f"{URL}/{row.uid}", json={"is_enabled": False})
    assert disable_resp.status_code == 200
    assert disable_resp.json()["data"]["is_enabled"] is False
    assert disable_resp.json()["data"]["is_main"] is False

    item = await _fetch_item(authed_client, row.name)
    assert item["is_enabled"] is False
    assert item["is_main"] is False

    # 3. OpenRouter drops the model — simulate what sync_model_type would do
    row.is_available = False
    db_session.add(row)
    await db_session.commit()

    # 4. gone from the default fetch view entirely
    resp = await authed_client.call("GET", URL, params={"search": row.name})
    assert resp.json()["data"]["paginated"] == []

    # 5. can no longer be re-enabled
    blocked_enable = await authed_client.call(
        "PATCH", f"{URL}/{row.uid}", json={"is_enabled": True}, raise_for_status=False
    )
    assert blocked_enable.status_code == 422

    # 6. and can't be set as main either
    blocked_main = await authed_client.call("PATCH", f"{URL}/{row.uid}/main", raise_for_status=False)
    assert blocked_main.status_code == 422
