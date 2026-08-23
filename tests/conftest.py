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
from services.mysql.model import Employees, PositionBackups

EMPLOYEE_STATUS_RESIGNED = 6
ALLOWED_PIC_POSITIONS = ["project manager", "assistant project manager"]


@pytest.fixture(scope="session")
def app():
    from apps.main import app

    return app


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
    # `basic_salary` is typed `float` on the model but stored as DECIMAL, so the DB
    # driver hands back a `Decimal` — model_dump() would otherwise warn about the
    # mismatch even though `Employees(**data)` below coerces it back to float fine.
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


class _FakeOpenRouterResponse:
    """Stands in for the subset of `httpx.Response` that
    `APIKeyManagementController.call_openrouter` actually reads."""

    def __init__(self, status_code: int, json_data: Optional[dict[str, Any]] = None):
        self.status_code = status_code
        self._json_data = json_data
        self.content = b"{}" if json_data is not None else b""
        self.headers: dict[str, str] = {}
        self.request = SimpleNamespace(url="https://openrouter.ai/api/v1/keys")

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
            )
        return _FakeOpenRouterResponse(200)


@pytest.fixture
def mock_openrouter(monkeypatch):
    """Bypasses every real OpenRouter call made through
    `apps.controller.api_key_management.call_openrouter` — the controller
    module's own `APICaller` reference is replaced, so this has no effect on
    `client`/`authed_client` (which hold their own `services.api_caller.APICaller`
    reference for talking to this app itself)."""
    monkeypatch.setattr("apps.controller.api_key_management.APICaller", _FakeOpenRouterCaller)


class _FakeModelSyncCall:
    """Per-test controllable stand-in for `services.openrouter.call_openrouter`,
    scoped to `apps.controller.model_management` only. Keyed by exact request
    `path` — the real controller reuses the identical `/videos/models` path for
    both the `video` and `image` types, so configuring that path answers both.

    Any path not explicitly `.set(...)` returns an error-shaped payload (no
    `data` key), which the controller's own guard treats as "unexpected
    response, skip this type" rather than "OpenRouter returned zero models" —
    critical here, since `df_engine_model_options` is shared, real, synced data:
    treating an unconfigured type as an empty list would flag every real row of
    that type unavailable the moment a test hits this endpoint.
    """

    def __init__(self) -> None:
        self.responses: dict[str, Any] = {}

    def set(self, path: str, items: list[dict[str, Any]]) -> None:
        self.responses[path] = {"data": items}

    async def __call__(self, db: Any, user_id: int, method: str, path: str, **kwargs: Any) -> Any:
        return self.responses.get(path, {"error": {"message": "not configured for this test"}})


@pytest.fixture
def mock_model_sync(monkeypatch):
    """Bypasses every real OpenRouter call made through the model-management
    sync endpoint. See `_FakeModelSyncCall` for why unconfigured paths must
    fail safe rather than default to an empty model list."""
    fake = _FakeModelSyncCall()
    monkeypatch.setattr("apps.controller.model_management.call_openrouter", fake)
    return fake
