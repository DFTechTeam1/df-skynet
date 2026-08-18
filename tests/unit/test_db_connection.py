import pytest
from unittest.mock import AsyncMock, MagicMock
from services.mysql import engine, get_db, make_session


def test_engine_is_cached_per_url():
    """Calling engine() twice with the same URL returns the identical cached instance."""
    first = engine("mysql+aiomysql://a:a@localhost:3306/db_a")
    second = engine("mysql+aiomysql://a:a@localhost:3306/db_a")
    assert first is second


def test_engine_differs_per_url():
    """Distinct URLs produce distinct, non-identical engine instances."""
    a = engine("mysql+aiomysql://a:a@localhost:3306/db_a")
    b = engine("mysql+aiomysql://b:b@localhost:3306/db_b")
    assert a is not b


def test_make_session_is_cached_per_url():
    """Calling make_session() twice with the same URL returns the identical cached sessionmaker."""
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
    """Session yielded by get_db() is committed, and never rolled back, when no exception is raised."""
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
    """Session yielded by get_db() is rolled back, and never committed, when the generator raises."""
    fake_session = _patch_make_session(monkeypatch)
    gen = get_db()
    session = await gen.__anext__()
    assert session is fake_session

    with pytest.raises(RuntimeError):
        await gen.athrow(RuntimeError("boom"))

    fake_session.rollback.assert_awaited_once()
    fake_session.commit.assert_not_awaited()
