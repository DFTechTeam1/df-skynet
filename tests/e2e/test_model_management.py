"""End-to-end journeys for model management: fetch and enable/disable chained
together. Deliberately never calls POST /models (sync) — that endpoint
reconciles a WHOLE usage type against OpenRouter and would mass-disable real,
already-synced rows if driven by a small fake response (see
tests/api/test_model_management_sync.py for how that's tested safely
instead). Journeys here start from rows created directly via the model
factory, standing in for "already synced" models, and only ever act on them
by uid.
"""

import pytest
from typing import Any
from sqlalchemy import update
from middlewares.lang import resolve_message
from services.mysql.factory.df_engine_model_options import DfEngineModelOptionsFactory
from services.mysql.model import DfEngineModelOptions
from services.redis import client as redis_client, delete_pattern

URL = "/api/models"


async def _fetch_item(authed_client, search: str) -> dict[str, Any]:
    resp = await authed_client.call("GET", URL, params={"search": search})
    items = resp.json()["data"]["paginated"]
    assert len(items) == 1, f"expected exactly one match for search={search!r}, got {items}"
    return items[0]


@pytest.mark.asyncio
async def test_main_model_cannot_be_disabled_then_sync_drop_blocks_actions_journey(authed_client, db_session):
    """A model holding is_main can't be disabled through the PATCH endpoint;
    once sync later flags it unavailable it disappears from the fetch list and
    can't be enabled either."""
    row = DfEngineModelOptionsFactory.create(type="image", is_available=True, is_enabled=True, is_main=True)

    # 1. confirmed live: enabled and main
    item = await _fetch_item(authed_client, row.name)
    assert item["is_enabled"] is True
    assert item["is_main"] is True

    # 2. disabling a main model is rejected — must hand off main to another model first
    disable_resp = await authed_client.call(
        "PATCH", f"{URL}/{row.uid}", json={"is_enabled": False}, raise_for_status=False
    )
    assert disable_resp.status_code == 422
    assert disable_resp.json()["message"] == resolve_message("model_option_main_cannot_be_disabled", "en")

    # 3. OpenRouter drops the model — simulate what sync does (flag unavailable,
    # then invalidate the model-option list cache). `row` belongs to the
    # factory's own sync session, so mutate it via a plain UPDATE on
    # `db_session` rather than re-`add`ing it to a second session.
    await db_session.execute(
        update(DfEngineModelOptions).where(DfEngineModelOptions.id == row.id).values(is_available=False)  # type: ignore
    )
    await db_session.commit()
    await delete_pattern(redis_client(), "model_option:*")

    # 4. gone from the default fetch view entirely
    resp = await authed_client.call("GET", URL, params={"search": row.name})
    assert resp.json()["data"]["paginated"] == []

    # 5. can no longer be toggled at all
    blocked_enable = await authed_client.call(
        "PATCH", f"{URL}/{row.uid}", json={"is_enabled": True}, raise_for_status=False
    )
    assert blocked_enable.status_code == 422
    assert blocked_enable.json()["message"] == resolve_message("model_option_unavailable_cannot_set_enabled", "en")
