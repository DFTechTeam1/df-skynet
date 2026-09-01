import re
import pytest
from datetime import datetime, timedelta
from services.mysql.factory import DfEngineOpenrouterLogsFactory
from services.api_key_management import ApiKeyManagement
from services.redis import client as redis_client, CacheKeys
from utils import local_time
from tests.helpers import clear_openrouter_logs

URL = "/api/key-management/logs"

HUMAN_DATE = re.compile(r"^\d{2} [A-Z][a-z]+ \d{4}, \d{2}:\d{2}$")
mask = ApiKeyManagement().mask_key
cache_key = CacheKeys()


@pytest.mark.asyncio
async def test_returns_logs_newest_first(authed_client, db_session):
    """200 OK; every OpenRouter call log is returned, newest first."""
    await clear_openrouter_logs(db_session)
    now = local_time()
    DfEngineOpenrouterLogsFactory.create(endpoint="/keys", method="POST", created_at=now - timedelta(minutes=5))
    DfEngineOpenrouterLogsFactory.create(endpoint="/keys/abc", method="DELETE", created_at=now)

    body = (await authed_client.call("GET", URL)).json()["data"]
    assert body["totalData"] == 2
    assert [row["endpoint"] for row in body["paginated"]] == ["/keys/abc", "/keys"]


@pytest.mark.asyncio
async def test_request_headers_are_never_exposed(authed_client, db_session):
    """200 OK; request_headers (carries the OpenRouter credential) is stripped; the rest kept."""
    await clear_openrouter_logs(db_session)
    DfEngineOpenrouterLogsFactory.create(
        name="Zola",
        method="POST",
        endpoint="/keys",
        request_headers={"Authorization": "Bearer sk-or-secret"},
        request_payload={"name": "new key"},
        response_status_code=201,
        response_headers={"x-ratelimit-remaining": "99"},
        response_body={"data": {"hash": "h"}},
        duration_ms=123,
    )

    row = (await authed_client.call("GET", URL)).json()["data"]["paginated"][0]
    assert "request_headers" not in row
    assert "id" not in row
    assert row["name"] == "Zola"
    assert row["request_payload"] == {"name": "new key"}
    assert row["response_headers"] == {"x-ratelimit-remaining": "99"}
    assert row["response_body"] == {"data": {"hash": "h"}}
    assert row["duration_ms"] == 123


@pytest.mark.asyncio
async def test_response_body_key_and_hash_are_masked(authed_client, db_session):
    """200 OK; the plaintext OpenRouter key and every 64-hex key hash are never returned in full."""
    await clear_openrouter_logs(db_session)
    real_key = "sk-or-v1-" + "d" * 56
    real_hash = "a" * 64
    DfEngineOpenrouterLogsFactory.create(
        method="POST",
        endpoint="https://openrouter.ai/api/v1/keys",
        response_status_code=201,
        response_headers={"location": f"/api/v1/keys/{real_hash}"},
        response_body={"key": real_key, "data": {"hash": real_hash, "name": "testing"}},
    )

    row = (await authed_client.call("GET", URL)).json()["data"]["paginated"][0]
    blob = str(row)
    assert real_key not in blob
    assert real_hash not in blob
    assert row["response_body"]["key"] == mask(real_key)
    assert row["response_body"]["data"]["hash"] == mask(real_hash)
    assert row["response_headers"]["location"] == f"/api/v1/keys/{mask(real_hash)}"
    assert row["response_body"]["data"]["name"] == "testing"


@pytest.mark.asyncio
async def test_hash_in_request_url_is_masked(authed_client, db_session):
    """200 OK; a DELETE/PATCH call logs the hash in the endpoint URL — that's masked too."""
    await clear_openrouter_logs(db_session)
    real_hash = "b" * 64
    DfEngineOpenrouterLogsFactory.create(method="DELETE", endpoint=f"https://openrouter.ai/api/v1/keys/{real_hash}")

    row = (await authed_client.call("GET", URL)).json()["data"]["paginated"][0]
    assert real_hash not in row["endpoint"]
    assert row["endpoint"] == f"https://openrouter.ai/api/v1/keys/{mask(real_hash)}"


@pytest.mark.asyncio
async def test_created_at_is_human_friendly(authed_client, db_session):
    """200 OK; created_at comes back as 'DD Month YYYY, HH:MM', not a raw timestamp."""
    await clear_openrouter_logs(db_session)
    DfEngineOpenrouterLogsFactory.create(created_at=datetime(2026, 1, 5, 9, 30))

    row = (await authed_client.call("GET", URL)).json()["data"]["paginated"][0]
    assert row["created_at"] == "05 January 2026, 09:30"
    assert HUMAN_DATE.match(row["created_at"])


@pytest.mark.asyncio
async def test_pagination(authed_client, db_session):
    """200 OK; page/itemsPerPage slice the log list."""
    await clear_openrouter_logs(db_session)
    now = local_time()
    for i in range(5):
        DfEngineOpenrouterLogsFactory.create(endpoint=f"/keys/{i}", created_at=now - timedelta(minutes=i))

    page_one = (await authed_client.call("GET", URL, params={"itemsPerPage": 2, "page": 1})).json()["data"]
    assert page_one["totalData"] == 5
    assert len(page_one["paginated"]) == 2

    page_three = (await authed_client.call("GET", URL, params={"itemsPerPage": 2, "page": 3})).json()["data"]
    assert len(page_three["paginated"]) == 1


@pytest.mark.asyncio
async def test_empty_table_returns_zero(authed_client, db_session):
    """200 OK; no logs yet -> empty list, totalData 0."""
    await clear_openrouter_logs(db_session)
    body = (await authed_client.call("GET", URL)).json()["data"]
    assert body["totalData"] == 0
    assert body["paginated"] == []


@pytest.mark.asyncio
async def test_rejects_out_of_range_params(authed_client, db_session):
    """422 when page < 1 or itemsPerPage over the cap."""
    await clear_openrouter_logs(db_session)
    assert (await authed_client.call("GET", URL, params={"page": 0}, raise_for_status=False)).status_code == 422
    assert (
        await authed_client.call("GET", URL, params={"itemsPerPage": 999}, raise_for_status=False)
    ).status_code == 422


@pytest.mark.asyncio
async def test_response_is_cached_with_a_ttl(authed_client, db_session):
    """200 OK; a GET populates the logs cache (keyed by page + page size) with an expiry."""
    await clear_openrouter_logs(db_session)
    DfEngineOpenrouterLogsFactory.create(endpoint="/keys")
    redis = redis_client()

    assert (await authed_client.call("GET", URL)).status_code == 200
    key = cache_key.api_key_management_logs(1, 50)
    assert await redis.exists(key)
    assert await redis.ttl(key) > 0


@pytest.mark.asyncio
async def test_second_fetch_is_served_from_cache(authed_client, db_session):
    """200 OK; once a page is cached, a row added afterwards isn't reflected until the cache is cleared."""
    await clear_openrouter_logs(db_session)
    DfEngineOpenrouterLogsFactory.create(endpoint="/keys")

    first = (await authed_client.call("GET", URL)).json()["data"]
    assert first["totalData"] == 1

    DfEngineOpenrouterLogsFactory.create(endpoint="/keys/xyz", method="DELETE")
    still_cached = (await authed_client.call("GET", URL)).json()["data"]
    assert still_cached["totalData"] == 1  # stale on purpose — served from cache

    await clear_openrouter_logs(db_session)
    DfEngineOpenrouterLogsFactory.create(endpoint="/keys")
    DfEngineOpenrouterLogsFactory.create(endpoint="/keys/xyz", method="DELETE")
    fresh = (await authed_client.call("GET", URL)).json()["data"]
    assert fresh["totalData"] == 2


@pytest.mark.asyncio
async def test_requires_auth(client):
    """401 when the request carries no bearer token."""
    resp = await client.call("GET", URL, raise_for_status=False)
    assert resp.status_code == 401
