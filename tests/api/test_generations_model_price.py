from datetime import timedelta
from uuid import uuid4
import pytest
import pytest_asyncio
from config.variables import USD_TO_IDR_RATE
from middlewares.lang import resolve_message
from services.mysql.factory.df_engine_generations import DfEngineGenerationsFactory
from services.mysql.factory.df_engine_model_options import DfEngineModelOptionsFactory
from services.mysql.factory.df_engine_menus import DfEngineMenusFactory
from services.mysql.factory.df_engine_features import DfEngineFeaturesFactory
from services.mysql.model.df_engine_generations import GenerationStatuses
from utils import local_time

URL = "/api/models-price"


def _url(model_uid):
    return f"{URL}/{model_uid}"


@pytest_asyncio.fixture
async def generation_fks(user_id) -> dict:
    """Self-contained menu/feature ids for df_engine_generations' NOT NULL FKs."""
    menu = DfEngineMenusFactory.create(created_by=int(user_id), df_engine_menu_feature_mapping=None)
    feature = DfEngineFeaturesFactory.create(created_by=int(user_id), df_engine_feature_prompt_mapping=None)
    return {"menu_id": menu.id, "feature_id": feature.id}


@pytest.mark.asyncio
async def test_averages_only_recent_successful_generations(authed_client, user_id, generation_fks):
    """Avg should include only in-window `success` rows, excluding `failed` and stale rows."""
    model = DfEngineModelOptionsFactory.create()
    common = dict(model_id=model.id, created_by=int(user_id), sourceable_id=1, **generation_fks)

    DfEngineGenerationsFactory.create(**common, status=GenerationStatuses.success, cost="0.10")
    DfEngineGenerationsFactory.create(**common, status=GenerationStatuses.success, cost="0.30")
    DfEngineGenerationsFactory.create(**common, status=GenerationStatuses.failed, cost="100.00")
    DfEngineGenerationsFactory.create(
        **common,
        status=GenerationStatuses.success,
        cost="999.00",
        created_at=local_time() - timedelta(days=100),
    )

    resp = await authed_client.call("GET", _url(model.uid))
    assert resp.status_code == 200
    body = resp.json()["data"]
    assert body["usd"] == "USD 0.20"
    assert body["idr"] == f"IDR {0.2 * float(USD_TO_IDR_RATE):,.0f}"


@pytest.mark.asyncio
async def test_no_matching_generations_returns_zero(authed_client):
    """A model with no success generations in-window reports a zero average, not an error."""
    model = DfEngineModelOptionsFactory.create()

    resp = await authed_client.call("GET", _url(model.uid))
    assert resp.status_code == 200
    assert resp.json()["data"] == {"usd": "USD 0", "idr": "IDR 0"}


@pytest.mark.asyncio
async def test_unknown_model_is_404(authed_client):
    resp = await authed_client.call("GET", _url(uuid4()), raise_for_status=False)
    assert resp.status_code == 404
    assert resp.json()["message"] == resolve_message("model_option_not_found", "en")


@pytest.mark.asyncio
async def test_requires_auth(client):
    resp = await client.call("GET", _url(uuid4()), raise_for_status=False)
    assert resp.status_code == 401
