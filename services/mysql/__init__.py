import traceback
from contextlib import contextmanager
from decimal import Decimal
from functools import lru_cache
from typing import Any, AsyncGenerator, Generator, Optional
from apps.secret import DB_ASYNC_URL, DB_SYNC_URL
from sqlalchemy import Engine, Result, Select, create_engine, select, text
from sqlalchemy.ext.asyncio import (
    create_async_engine,
    async_sessionmaker,
    AsyncEngine,
    AsyncSession,
)
from sqlalchemy.orm import Session, scoped_session, sessionmaker
from sqlmodel import SQLModel
from log import logging


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
    # ponytail: pymysql defaults to no timeouts, so a half-dead socket blocks a worker forever; pre_ping drops stale pooled conns.
    return create_engine(
        db_url,
        pool_recycle=1800,
        pool_pre_ping=True,
        connect_args={"connect_timeout": 10, "read_timeout": 15, "write_timeout": 15},
    )


@lru_cache
def make_sync_session(db_url: str) -> scoped_session[Session]:
    return scoped_session(sessionmaker(bind=sync_engine(db_url), autoflush=False, expire_on_commit=False))


@contextmanager
def get_sync_db() -> Generator[Session, None, None]:
    with make_sync_session(DB_SYNC_URL)() as session:
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with make_session(DB_ASYNC_URL)() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


def _label_duplicates(columns: tuple[Any, ...]) -> tuple[Any, ...]:
    """Label ORM attributes that share a key (e.g. `Employees.id` + `ApiKeys.id` across a join)
    as `<table>_<key>` so Row access isn't ambiguous. Existing `.label(...)`s are left alone."""
    keys = [getattr(c, "key", None) for c in columns]
    dup = {k for k in keys if k and keys.count(k) > 1}
    return tuple(
        c.label(f"{c.class_.__tablename__}_{k}") if k in dup and hasattr(c, "class_") else c
        for c, k in zip(columns, keys)
    )


def _build_stmt(
    table: type[SQLModel],
    columns: Optional[tuple[Any, ...]],
    joins: Optional[tuple[Any, ...]],
    filters: Optional[tuple[Any, ...]],
    options: Optional[tuple[Any, ...]],
    order_by: Optional[tuple[Any, ...]],
    limit: Optional[int],
    offset: Optional[int],
    fetch_one: bool,
) -> Select[Any]:
    columns = _label_duplicates(columns) if columns else columns
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

    if filters is not None:
        stmt = stmt.where(*filters)

    if order_by is not None:
        stmt = stmt.order_by(*order_by)

    if limit is None and fetch_one:
        limit = 1

    if limit is not None:
        stmt = stmt.limit(limit)

    if offset is not None:
        stmt = stmt.offset(offset)

    return stmt


def _fetch(result: Result[Any], columns: Optional[tuple[Any, ...]], fetch_one: bool) -> Any:
    scalar = not columns or len(columns) == 1

    if fetch_one:
        return result.scalars().first() if scalar else result.first()
    return result.scalars().all() if scalar else result.all()


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
    `Row` tuples. Columns sharing a key across joined tables are labelled
    `<table>_<key>`. To narrow the root table while keeping entities (e.g. when
    ORM-mutating or using `options`), pass `load_only(...)` inside `options`.
    `fetch_one`: return a single result (or `None`) instead of a list — the
    shape (model instance / scalar / `Row`) follows `columns` the same way.
    Implies `limit=1` when `limit` isn't set, so only one row is fetched.
    """
    stmt = _build_stmt(table, columns, joins, filters, options, order_by, limit, offset, fetch_one)
    return _fetch(await db.execute(stmt), columns, fetch_one)


def query_sync(
    db: Session,
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
    """Sync mirror of `query()` for Celery tasks — same SELECT-builder, same
    signature, `db.execute(stmt)` without `await`."""
    stmt = _build_stmt(table, columns, joins, filters, options, order_by, limit, offset, fetch_one)
    return _fetch(db.execute(stmt), columns, fetch_one)


def get_usd_rate(db: Session) -> Decimal:
    """USD->base-currency rate from the `get_currency_rate` procedure; 0 if the call fails."""
    try:
        row = db.execute(text("CALL get_currency_rate('USD')")).fetchone()
        return Decimal(str(row[0])) if row else Decimal("0")
    except Exception:
        logging.error(f"get_usd_rate failed, storing 0: {traceback.format_exc()}")
        return Decimal("0")
