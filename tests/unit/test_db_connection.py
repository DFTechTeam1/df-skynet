import pytest
from unittest.mock import AsyncMock, MagicMock
from services.mysql import engine, get_db, make_session

def test_engine_is_cached_per_url():
    first = engine("mysql+aiomysql://a:a@localhost:3306/db_a")
    second = engine("mysql+aiomysql://a:a@localhost:3306/db_a")
    assert first is second


def test_engine_differs_per_url():
    a = engine("mysql+aiomysql://a:a@localhost:3306/db_a")
    b = engine("mysql+aiomysql://b:b@localhost:3306/db_b")
    assert a is not b


def test_make_session_is_cached_per_url():
    first = make_session("mysql+aiomysql://a:a@localhost:3306/db_a")
    second = make_session("mysql+aiomysql://a:a@localhost:3306/db_a")
    assert first is second


def _patch_make_session(monkeypatch) -> AsyncMock:
    fake_session = AsyncMock()
    fake_sessionmaker = MagicMock(return_value=fake_session)
    fake_session.__aenter__ = AsyncMock(return_value=fake_session)
    fake_session.__aexit__ = AsyncMock(return_value=False)
    monkeypatch.setattr("services.mysql.make_session", lambda url: fake_sessionmaker)
    return fake_session


@pytest.mark.asyncio
async def test_get_db_commits_on_success(monkeypatch):
    fake_session = _patch_make_session(monkeypatch)
    gen = get_db()
    session = await gen.__anext__()
    assert session is fake_session

    with pytest.raises(StopAsyncIteration):
        await gen.__anext__()

    fake_session.commit.assert_awaited_once()
    fake_session.rollback.assert_not_awaited()


@pytest.mark.asyncio
async def test_get_db_rolls_back_on_exception(monkeypatch):
    fake_session = _patch_make_session(monkeypatch)
    gen = get_db()
    session = await gen.__anext__()
    assert session is fake_session

    with pytest.raises(RuntimeError):
        await gen.athrow(RuntimeError("boom"))

    fake_session.rollback.assert_awaited_once()
    fake_session.commit.assert_not_awaited()
