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
