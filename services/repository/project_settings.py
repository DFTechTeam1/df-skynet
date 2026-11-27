from typing import Any, Optional
from services.mysql.model import DfEngineProjectSettings
from services.repository.base import BaseRepository


class ProjectSettingRepository(BaseRepository):
    async def get_project_setting(
        self,
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
        return await self._get(
            DfEngineProjectSettings,
            (),
            "project_setting_not_found",
            filters,
            columns,
            options,
            joins,
            raise_if_null,
            context,
            fetch_one,
            limit,
            group_by,
            having,
            order_by,
            offset,
        )

    async def upsert(self, row: dict[str, Any]) -> None:
        """Insert a project's override, or update it if the project already has one. Doesn't commit."""
        await self._upsert(DfEngineProjectSettings, [row], keep_columns=("project_id", "created_at", "created_by"))
