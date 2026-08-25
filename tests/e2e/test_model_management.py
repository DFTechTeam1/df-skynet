"""End-to-end journeys for model management: fetch and enable/disable chained
together. Deliberately never calls POST /models (sync) — that endpoint
reconciles a WHOLE usage type against OpenRouter and would mass-disable real,
already-synced rows if driven by a small fake response (see
tests/api/test_model_management_sync.py for how that's tested safely
instead). Journeys here start from rows created directly via `create_record`,
standing in for "already synced" models, and only ever act on them by uid.
"""

import pytest
from typing import Any
from uuid import uuid4
from services.mysql.model import DfEngineModelOptions
from tests.helpers import create_record

URL = "/api/models"


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
async def test_disable_cascades_then_unavailable_blocks_actions_journey(authed_client, db_session):
    """Disabling a main model cascades to clear is_main; once the model is
    later flagged unavailable (as sync would do), it disappears from the
    fetch list and enable/disable is rejected."""
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
