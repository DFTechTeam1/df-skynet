from typing import Any, Optional
from services.mysql.model import EntertainmentTaskSongs, ProjectSongLists, Projects, ProjectTasks
from services.repository.base import BaseRepository


class ProjectRepository(BaseRepository):
    """Lookups for projects and their tasks (production tasks and entertainment songs).

    Every `get_*` method takes the same arguments and returns the same thing:

    Args:
        filters: SQLAlchemy conditions that identify the row,
            e.g. `(Projects.uid == project_uid,)`.
        columns: Columns to return. Each method documents its own default.
        options: SQLAlchemy loader options, e.g. `(selectinload(Projects.project_tasks),)`.
        joins: Tables to join, each a join target (e.g. `Projects.project_tasks`) or an explicit
            `(target, onclause)` / `(target, onclause, is_outer)` tuple.
        limit: Maximum rows the database reads. Defaults to 1; only the first row is ever returned.
        raise_if_null: Raise an error when nothing matches (default `True`).
            Set to `False` to get `None` back instead.
        context: Values that fill `{placeholders}` in the not-found message,
            e.g. `{"uid": project_uid}` for "Project {uid} not found." Ignored if the message has none.

    Returns:
        A `Row` with the requested columns. Read values as attributes, e.g. `project.name`.
        If only one column is requested, that value is returned directly instead of a `Row`.
        `None` when nothing matches and `raise_if_null=False`.

    Example:
        >>> repo = ProjectRepository(db)
        >>> project = await repo.get_project((Projects.uid == project_uid,))
        >>> project.name, project.classification, project.status
        >>> task = await repo.get_production_task((ProjectTasks.uid == uid,), raise_if_null=False)  # None if missing
    """

    async def get_project(
        self,
        filters: tuple[Any, ...],
        columns: Optional[tuple[Any, ...]] = None,
        options: Optional[tuple[Any, ...]] = None,
        joins: Optional[tuple[Any, ...]] = None,
        limit: Optional[int] = None,
        raise_if_null: bool = True,
        context: Optional[dict[str, Any]] = None,
    ) -> Any:
        """Get a single project. Columns default to `name`, `classification` and `status`.

        Raises:
            DataValidationError: `project_not_found` (HTTP 422) when nothing matches
                and `raise_if_null=True`.
        """
        return await self._get_one(
            Projects,
            (Projects.name, Projects.classification, Projects.status),
            "project_not_found",
            filters,
            columns,
            options,
            joins,
            limit,
            raise_if_null,
            context,
        )

    async def get_production_task(
        self,
        filters: tuple[Any, ...],
        columns: Optional[tuple[Any, ...]] = None,
        options: Optional[tuple[Any, ...]] = None,
        joins: Optional[tuple[Any, ...]] = None,
        limit: Optional[int] = None,
        raise_if_null: bool = True,
        context: Optional[dict[str, Any]] = None,
    ) -> Any:
        """Get a single production task (`project_tasks` table).

        Columns default to `id`, `uid`, `project_id`, `name` and `status`.

        Raises:
            DataValidationError: `project_task_not_found` (HTTP 422) when nothing matches
                and `raise_if_null=True`.
        """
        return await self._get_one(
            ProjectTasks,
            (ProjectTasks.id, ProjectTasks.uid, ProjectTasks.project_id, ProjectTasks.name, ProjectTasks.status),
            "project_task_not_found",
            filters,
            columns,
            options,
            joins,
            limit,
            raise_if_null,
            context,
        )

    async def get_entertainment_task(
        self,
        filters: tuple[Any, ...],
        columns: Optional[tuple[Any, ...]] = None,
        options: Optional[tuple[Any, ...]] = None,
        joins: Optional[tuple[Any, ...]] = None,
        limit: Optional[int] = None,
        raise_if_null: bool = True,
        context: Optional[dict[str, Any]] = None,
    ) -> Any:
        """Get a single entertainment task, which is a song (`project_song_lists` table).

        Columns default to `id`, `uid`, `project_id`, `name` and `status`. A song has no status of
        its own: `status` comes from `entertainment_task_songs` (left-joined, so it is `None` when
        the song has no assignment yet). If a song has several assignments, the first one is used.

        Raises:
            DataValidationError: `project_song_not_found` (HTTP 422) when nothing matches
                and `raise_if_null=True`.
        """
        joins = (
            (EntertainmentTaskSongs, EntertainmentTaskSongs.project_song_list_id == ProjectSongLists.id, True),
            *(joins or ()),
        )
        return await self._get_one(
            ProjectSongLists,
            (
                ProjectSongLists.id,
                ProjectSongLists.uid,
                ProjectSongLists.project_id,
                ProjectSongLists.name,
                EntertainmentTaskSongs.status,
            ),
            "project_song_not_found",
            filters,
            columns,
            options,
            joins,
            limit,
            raise_if_null,
            context,
        )
