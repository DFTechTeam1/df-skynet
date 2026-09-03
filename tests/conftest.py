from types import SimpleNamespace
from typing import Any, Optional
import pytest
import pytest_asyncio
from httpx import ASGITransport
from jose import jwt
from sqlalchemy import func, select
from uuid import uuid4
from apps.secret import DB_ASYNC_URL, ERP_EMAIL, ERP_PASSWORD, LOGIN_URL
from services.api_caller import APICaller
from services.mysql import make_session
from services.mysql.model import Employees, PositionBackups, ProjectClasses, Projects

EMPLOYEE_STATUS_RESIGNED = 6
ALLOWED_PIC_POSITIONS = ["project manager", "assistant project manager"]


@pytest.fixture(scope="session")
def app():
    from apps.main import app

    return app


@pytest.fixture(autouse=True)
def _reset_rate_limiter():
    """`rate_limit()` builds one `RateLimiter` (and its `KeyedBucketFactory`)
    per controller class at import time, shared for the life of the process —
    not per request or per test. A path with no path params (e.g. `/api/setting`)
    keys to a single bucket for the whole test run, so a test file that legitimately
    calls the same fixed path many times (unlike `/api/models/{uid}`, where a random
    uid gives every call its own bucket) can trip the real 15/second cap purely from
    test volume. Clearing every bucket before each test keeps that budget scoped to
    the current test instead of accumulating across the whole session.
    """
    from apps.controller.core import CoreDependencies

    CoreDependencies.throttle.dependency.limiter.bucket_factory.buckets.clear()
    yield


@pytest_asyncio.fixture(autouse=True)
async def _clear_all_redis_caches():
    """Every controller now caches its GET responses in Redis. Tests build
    state either through the API itself (which invalidates its own cache on
    every write) or directly via SQLModel factories / raw DB deletes, which
    bypass that invalidation entirely. A stale cache entry left by an earlier
    test can then hide a later test's freshly-inserted (or freshly-removed)
    row, regardless of which file that earlier test lived in. Clearing every
    known cache namespace before each test keeps the whole suite cache-cold
    by default — one blanket fix instead of chasing down every individual
    factory-then-GET combination file by file.
    """
    from services.redis import client as redis_client, delete_pattern

    redis = redis_client()
    for pattern in (
        "feature_management:list:*",
        "feature_management:detail:*",
        "menu_management:list:*",
        "menu_management:detail:*",
        "prompt_template:list:*",
        "prompt_template:detail:*",
        "model_option:*",
        "api_key_management:*",
        "setting:detail:*",
        "setting:logs:*",
        "user_preference:*",
    ):
        await delete_pattern(redis, pattern)
    yield


@pytest_asyncio.fixture
async def db_session():
    async with make_session(DB_ASYNC_URL)() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


@pytest_asyncio.fixture(scope="session")
async def access_token() -> str:
    async with APICaller() as caller:
        resp = await caller.call(
            "POST",
            f"{LOGIN_URL}/auth/login",
            json={"email": ERP_EMAIL, "password": ERP_PASSWORD, "remember_me": True},
            headers={"Accept": "application/json"},
        )
        return resp.json()["data"]["access_token"]


@pytest.fixture(scope="session")
def user_id(access_token: str) -> str:
    return jwt.get_unverified_claims(access_token)["sub"]


@pytest_asyncio.fixture
async def client(app):
    async with APICaller(transport=ASGITransport(app=app), base_url="http://test") as caller:
        yield caller


@pytest_asyncio.fixture
async def authed_client(app, access_token):
    async with APICaller(
        transport=ASGITransport(app=app),
        base_url="http://test",
        headers={"Authorization": f"Bearer {access_token}"},
    ) as caller:
        yield caller


async def _any_employee_template(db_session) -> Employees:
    template = (await db_session.execute(select(Employees).limit(1))).scalars().first()
    assert template is not None, "staging DB has no employee row to clone from for API key management fixtures"
    return template


async def _create_employee(db_session, **overrides) -> Employees:
    """Clone an arbitrary existing employee row into a fresh one, overriding
    whatever the caller needs (status, position_id, ...). Only inserts a new
    row — never mutates the template. Unique-ish columns (email, phone,
    id_number, employee_id, uid) are always randomized to dodge collisions;
    `user_id` is cleared since `employees.user_id` is effectively one-to-one
    with `users`.
    """
    template = await _any_employee_template(db_session)
    suffix = uuid4().hex[:10]
    data = template.model_dump(exclude={"id"}, warnings=False)
    data.update(
        uid=str(uuid4()),
        email=f"test-{suffix}@example.com",
        personal_email=None,
        phone=str(uuid4().int)[:15],
        id_number=uuid4().hex[:16],
        employee_id=f"test-{suffix}",
        user_id=None,
    )
    data.update(overrides)

    row = Employees(**data)
    db_session.add(row)
    await db_session.commit()
    await db_session.refresh(row)
    return row


@pytest_asyncio.fixture
async def active_employee_uid(db_session) -> str:
    """uid of a fresh, non-resigned employee holding an allowed PIC position
    (Project Manager / Assistant Project Manager) — a valid `employee_uid`
    fixture for API key management tests.

    Cloned from an arbitrary existing employee row rather than searched for,
    since staging isn't guaranteed to already have one on hand with this
    exact position.
    """
    position = (
        (
            await db_session.execute(
                select(PositionBackups).where(func.lower(PositionBackups.name).in_(ALLOWED_PIC_POSITIONS))
            )
        )
        .scalars()
        .first()
    )
    assert position is not None, (
        "staging DB has no Project Manager / Assistant Project Manager position to fixture against"
    )

    row = await _create_employee(db_session, status=1, position_id=position.id)
    return row.uid


@pytest_asyncio.fixture
async def resigned_employee_uid(db_session) -> str:
    """uid of an employee with `status == 6` (resigned) — exercises the resigned-PIC guard."""
    row = await _create_employee(db_session, status=EMPLOYEE_STATUS_RESIGNED)
    return row.uid


@pytest_asyncio.fixture
async def wrong_position_employee_uid(db_session) -> str:
    """uid of a non-resigned employee holding a position other than Project
    Manager / Assistant Project Manager — exercises the position guard."""
    position = (
        (
            await db_session.execute(
                select(PositionBackups).where(func.lower(PositionBackups.name).notin_(ALLOWED_PIC_POSITIONS))
            )
        )
        .scalars()
        .first()
    )
    assert position is not None, "staging DB has no non-PM/APM position to fixture against"

    row = await _create_employee(db_session, status=1, position_id=position.id)
    return row.uid


@pytest_asyncio.fixture
async def project_uid(db_session) -> str:
    """uid of an arbitrary existing project — the setting endpoints validate the
    `project_limit_override` target against `projects.uid`."""
    row = (await db_session.execute(select(Projects).limit(1))).scalars().first()
    assert row is not None, "staging DB has no project row to fixture against"
    return row.uid


@pytest_asyncio.fixture
async def project_class_id(db_session) -> int:
    """id of an arbitrary existing project class — for the per-class limits payload."""
    row = (await db_session.execute(select(ProjectClasses).limit(1))).scalars().first()
    assert row is not None, "staging DB has no project_classes row to fixture against"
    return row.id


class _FakeOpenRouterResponse:
    """Stands in for the subset of `httpx.Response` the API key management
    controller reads off an OpenRouter call: status_code, is_error, content,
    text, headers, request.url, and .json()."""

    def __init__(self, status_code: int, json_data: Optional[dict[str, Any]] = None, path: str = "/keys"):
        self.status_code = status_code
        self.is_error = status_code >= 400
        self._json_data = json_data
        self.content = b"{}" if json_data is not None else b""
        self.text = "{}" if json_data is not None else ""
        self.headers: dict[str, str] = {}
        self.request = SimpleNamespace(url=f"https://openrouter.ai/api/v1{path}")

    def json(self) -> dict[str, Any]:
        return self._json_data or {}


class _FakeOpenRouterCaller:
    """Drop-in replacement for `services.api_caller.APICaller` scoped to
    `apps.controller.api_key_management` only — fabricates OpenRouter
    responses instead of making a real HTTP call, so tests never touch a
    real OpenRouter account. POST /keys returns a fresh, unique key/hash
    pair each call; PATCH/DELETE return an empty 200 (matching a real
    disable/delete call)."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        pass

    async def __aenter__(self) -> "_FakeOpenRouterCaller":
        return self

    async def __aexit__(self, *args: Any) -> None:
        return None

    async def call(self, method: str, path: str, json: Optional[dict[str, Any]] = None, **kwargs: Any):
        if method == "POST":
            return _FakeOpenRouterResponse(
                201,
                {"key": f"sk-or-v1-fake{uuid4().hex}", "data": {"hash": uuid4().hex}},
                path=path,
            )
        return _FakeOpenRouterResponse(200, path=path)


@pytest.fixture
def mock_openrouter(monkeypatch):
    """Bypasses every real OpenRouter call made through
    `apps.controller.api_key_management.call_openrouter` — the controller
    module's own `APICaller` reference is replaced, so this has no effect on
    `client`/`authed_client` (which hold their own `services.api_caller.APICaller`
    reference for talking to this app itself)."""
    monkeypatch.setattr("apps.controller.api_key_management.APICaller", _FakeOpenRouterCaller)


class _FakeModelSyncResponse:
    """Stands in for the subset of `httpx.Response` that the sync endpoint
    reads off an OpenRouter call."""

    def __init__(self, status_code: int, payload: Optional[dict[str, Any]], path: str):
        self.status_code = status_code
        self._payload = payload
        self.content = b"{}" if payload is not None else b""
        self.headers: dict[str, str] = {}
        self.request = SimpleNamespace(url=f"https://openrouter.ai/api/v1{path}")
        self.is_error = status_code >= 400

    def json(self) -> dict[str, Any]:
        return self._payload or {}


class _FakeModelSyncCaller:
    """Drop-in replacement for `APICaller` scoped to
    `apps.controller.model_management`. `GET` returns a 200 `{"data": [...]}`
    for any path a test configured via `mock_model_sync.set(path, items)`;
    an unconfigured path returns a 5xx so the endpoint's `is_error` guard
    skips that usage type instead of treating it as "OpenRouter returned zero
    models" — critical, since `df_engine_model_options` is shared, real data
    and an empty list would flag every row of that type unavailable.
    """

    responses: dict[str, list[dict[str, Any]]] = {}

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        pass

    async def __aenter__(self) -> "_FakeModelSyncCaller":
        return self

    async def __aexit__(self, *args: Any) -> None:
        return None

    async def call(
        self, method: str, path: str, raise_for_status: bool = True, **kwargs: Any
    ) -> _FakeModelSyncResponse:
        if path in self.responses:
            return _FakeModelSyncResponse(200, {"data": self.responses[path]}, path)
        return _FakeModelSyncResponse(502, {"error": {"message": "not configured for this test"}}, path)


@pytest.fixture
def mock_model_sync(monkeypatch):
    """Bypasses every real OpenRouter call made through the model-management
    sync endpoint. `.set(path, items)` configures one usage type's response;
    the endpoint's paths are `/models?output_modalities=text`, `/videos/models`
    and `/images/models`. See `_FakeModelSyncCaller` for why unconfigured
    paths fail safe rather than default to an empty model list."""
    _FakeModelSyncCaller.responses = {}
    monkeypatch.setattr("apps.controller.model_management.APICaller", _FakeModelSyncCaller)
    return SimpleNamespace(set=lambda path, items: _FakeModelSyncCaller.responses.__setitem__(path, items))
