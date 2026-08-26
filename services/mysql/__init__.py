from functools import lru_cache
from typing import Any, AsyncGenerator, Optional
from apps.secret import DB_ASYNC_URL
from sqlalchemy import Engine, create_engine, select
from sqlalchemy.ext.asyncio import (
    create_async_engine,
    async_sessionmaker,
    AsyncEngine,
    AsyncSession,
)
from sqlalchemy.orm import Session, scoped_session, sessionmaker
from sqlmodel import SQLModel


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


@lru_cache
def sync_engine(db_url: str) -> Engine:
    """Sync counterpart to `engine()` — needed by SQLAlchemyModelFactory (see
    services/mysql/factory/base.py), which requires a sync Session to persist.
    The app itself stays async-only; this pool exists only for factories/tests.
    """
    return create_engine(db_url, pool_recycle=1800)


@lru_cache
def make_sync_session(db_url: str) -> scoped_session[Session]:
    return scoped_session(sessionmaker(bind=sync_engine(db_url), autoflush=False, expire_on_commit=False))


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with make_session(DB_ASYNC_URL)() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def query(
    db: AsyncSession,
    table: type[SQLModel],
    columns: Optional[tuple[Any, ...]] = None,
    joins: Optional[tuple[Any, ...]] = None,
    filters: Optional[tuple[Any, ...]] = None,
    options: Optional[tuple[Any, ...]] = None,
    order_by: Optional[tuple[Any, ...]] = None,
    limit: Optional[int] = None,
    offset: Optional[int] = None,
    fetch_one: bool = False,
) -> Any:
    """Generic SELECT builder so controllers don't hand-roll a query method per
    relation/filter/paging combination.

    `joins`: each item is either a join target (implicit join, e.g. via a
    declared relationship) or an explicit `(target, onclause)` /
    `(target, onclause, is_outer)` tuple.
    `columns`: omitted selects whole `table` rows, returned as model
    instances; one column/entity returns that value; two or more return
    `Row` tuples.
    `fetch_one`: return a single result (or `None`) instead of a list — the
    shape (model instance / scalar / `Row`) follows `columns` the same way.
    Implies `limit=1` when `limit` isn't set, so only one row is fetched.
    """
    stmt = select(*columns) if columns else select(table)

    if joins:
        for join in joins:
            if isinstance(join, tuple):
                if len(join) == 3:
                    target, onclause, is_outer = join
                    stmt = stmt.join(target, onclause, isouter=is_outer)
                else:
                    target, onclause = join
                    stmt = stmt.join(target, onclause)
            else:
                stmt = stmt.join(join)

    if options:
        stmt = stmt.options(*options)

    if filters:
        stmt = stmt.where(*filters)

    if order_by:
        stmt = stmt.order_by(*order_by)

    if limit is None and fetch_one:
        limit = 1

    if limit is not None:
        stmt = stmt.limit(limit)

    if offset is not None:
        stmt = stmt.offset(offset)

    result = await db.execute(stmt)
    scalar = not columns or len(columns) == 1

    if fetch_one:
        return result.scalars().first() if scalar else result.first()
    return result.scalars().all() if scalar else result.all()
