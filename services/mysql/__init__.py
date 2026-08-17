from functools import lru_cache
from typing import AsyncGenerator
from apps.secret import DB_ASYNC_URL
from sqlalchemy.ext.asyncio import (
    create_async_engine,
    async_sessionmaker,
    AsyncEngine,
    AsyncSession,
)


@lru_cache
def engine(db_url: str) -> AsyncEngine:
    """One engine (and its connection pool) per distinct `db_url`, built once
    and reused. Without caching, every call would spin up a brand new pool.
    """
    return create_async_engine(db_url, pool_size=10, max_overflow=20, pool_recycle=1800)


@lru_cache
def make_session(db_url: str) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(
        bind=engine(db_url),
        autoflush=False,
        expire_on_commit=False,
    )


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with make_session(DB_ASYNC_URL)() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
