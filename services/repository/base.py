from typing import Any, Optional
from sqlalchemy import update
from sqlalchemy.dialects.mysql import insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import SQLModel
from error import DataNotFoundError
from services.mysql import query
from utils.serializer import serialize


class BaseRepository:
    """Base class for repositories. Holds the database session and the shared query helpers.

    Subclass it and add one method per lookup, built on `_get`:

        class ProjectRepository(BaseRepository):
            async def get_project(self, filters, columns=None, options=None, raise_if_null=True):
                return await self._get(Projects, (Projects.name,), "project_not_found", ...)

    Args:
        db: Async database session, shared by every method of the repository.
    """

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def _get(
        self,
        table: type[SQLModel],
        default_columns: tuple[Any, ...],
        not_found_message: str,
        filters: Optional[tuple[Any, ...]] = None,
        columns: Optional[tuple[Any, ...]] = None,
        options: Optional[tuple[Any, ...]] = None,
        joins: Optional[tuple[Any, ...]] = None,
        raise_if_null: bool = True,
        context: Optional[dict[str, Any]] = None,
        fetch_one: bool = True,
        limit: Optional[int] = None,
        group_by: Optional[tuple[Any, ...]] = None,
        having: Optional[tuple[Any, ...]] = None,
        order_by: Optional[tuple[Any, ...]] = None,
        offset: Optional[int] = None,
    ) -> Any:
        """Fetch one row (default) or every matching row from `table`.

        Args:
            table: The model to read from.
            default_columns: Columns returned when `columns` is not given.
            not_found_message: Error message key raised when nothing matches.
            filters: SQLAlchemy conditions that identify the row.
            columns: Columns to return. Defaults to `default_columns`.
            options: SQLAlchemy loader options, e.g. `(selectinload(Projects.project_tasks),)`.
            joins: Tables to join, each a join target (e.g. a relationship) or an explicit
                `(target, onclause)` / `(target, onclause, is_outer)` tuple.
            raise_if_null: Raise an error when no row matches (default `True`).
                Set to `False` to get `None` (or `[]` when `fetch_one=False`) back instead.
            context: Values that fill `{placeholders}` in the error message, e.g. `{"uid": uid}`
                for a message like "Project {uid} not found." Ignored if the message has none.
            fetch_one: `True` (default) returns the first match only; `False` returns a list
                of every match.
            limit: Maximum rows the database reads. Defaults to 1 when `fetch_one=True`,
                unlimited when `fetch_one=False`.
            group_by: Expressions for `GROUP BY`, e.g. `(Projects.status,)`. Pair with an
                aggregate in `columns` and `fetch_one=False` to get every group.
            having: Conditions on aggregates, e.g. `(func.count(Projects.id) > 1,)`.
            order_by: Sort expressions, e.g. `(Projects.created_at.desc(),)`.
            offset: Rows to skip; pair with `limit` and `fetch_one=False` to paginate.

        Returns:
            A `Row` with the requested columns (a single value if only one column is requested).
            `None` (`[]` when `fetch_one=False`) when nothing matches and `raise_if_null=False`.

        Raises:
            DataNotFoundError: `not_found_message` (HTTP 404) when no row matches
                and `raise_if_null=True`.
        """
        row = await query(
            db=self.db,
            table=table,
            columns=columns or default_columns,
            joins=joins,
            filters=filters,
            options=options,
            limit=limit,
            fetch_one=fetch_one,
            group_by=group_by,
            having=having,
            order_by=order_by,
            offset=offset,
        )
        if (row is None or (not fetch_one and not row)) and raise_if_null:
            raise DataNotFoundError(message=not_found_message, context=context)
        return serialize(row)

    async def _update(self, table: type[SQLModel], filters: tuple[Any, ...], values: dict[str, Any]) -> None:
        """Set `values` on every row of `table` that matches `filters`. Doesn't commit.

        `filters` is required, so a whole table can't be updated by leaving it out.
        """
        await self.db.execute(update(table).where(*filters).values(**values))

    async def _upsert(self, table: type[SQLModel], rows: list[dict[str, Any]], keep_columns: tuple[str, ...]) -> None:
        """Insert `rows` into `table`. A row that hits a primary or unique key is updated instead. Doesn't commit.

        MySQL only. Every row must have the same keys, including all required columns.
        `keep_columns` are written on insert but left unchanged on existing rows; columns
        absent from `rows` are left unchanged too.
        """
        stmt = insert(table).values(rows)
        await self.db.execute(
            stmt.on_duplicate_key_update({key: stmt.inserted[key] for key in rows[0] if key not in keep_columns})
        )
