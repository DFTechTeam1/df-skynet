import pytest
import pytest_asyncio
from httpx import ASGITransport
from jose import jwt
from apps.secret import DB_ASYNC_URL, ERP_EMAIL, ERP_PASSWORD, LOGIN_URL
from services.api_caller import APICaller
from services.mysql import make_session


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
    async with APICaller(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as caller:
        yield caller


@pytest_asyncio.fixture
async def authed_client(app, access_token):
    async with APICaller(
        transport=ASGITransport(app=app),
        base_url="http://test",
        headers={"Authorization": f"Bearer {access_token}"},
    ) as caller:
        yield caller
