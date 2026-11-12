from typing import Any, Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import SQLModel
from error import DataValidationError
from services.mysql import query


class BaseRepository:
    """Base class for repositories. Holds the database session and the shared query helpers.

    Subclass it and add one method per lookup, built on `_get_one`:

        class ProjectRepository(BaseRepository):
            async def get_project(self, filters, columns=None, options=None, raise_if_null=True):
                return await self._get_one(Projects, (Projects.name,), "project_not_found", ...)

    Args:
        db: Async database session, shared by every method of the repository.
    """

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def _get_one(
        self,
        table: type[SQLModel],
        default_columns: tuple[Any, ...],
        not_found_message: str,
        filters: tuple[Any, ...],
        columns: Optional[tuple[Any, ...]] = None,
        options: Optional[tuple[Any, ...]] = None,
        joins: Optional[tuple[Any, ...]] = None,
        limit: Optional[int] = None,
        raise_if_null: bool = True,
        context: Optional[dict[str, Any]] = None,
    ) -> Any:
        """Fetch a single row from `table`.

        Args:
            table: The model to read from.
            default_columns: Columns returned when `columns` is not given.
            not_found_message: Error message key raised when nothing matches.
            filters: SQLAlchemy conditions that identify the row.
            columns: Columns to return. Defaults to `default_columns`.
            options: SQLAlchemy loader options, e.g. `(selectinload(Projects.project_tasks),)`.
            joins: Tables to join, each a join target (e.g. a relationship) or an explicit
                `(target, onclause)` / `(target, onclause, is_outer)` tuple.
            limit: Maximum rows the database reads. Defaults to 1; only the first row is
                ever returned.
            raise_if_null: Raise an error when no row matches (default `True`).
                Set to `False` to get `None` back instead.
            context: Values that fill `{placeholders}` in the error message, e.g. `{"uid": uid}`
                for a message like "Project {uid} not found." Ignored if the message has none.

        Returns:
            A `Row` with the requested columns (a single value if only one column is requested).
            `None` when nothing matches and `raise_if_null=False`.

        Raises:
            DataValidationError: `not_found_message` (HTTP 422) when no row matches
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
            fetch_one=True,
        )
        if row is None and raise_if_null:
            raise DataValidationError(message=not_found_message, context=context)
        return row
