import json
from typing import Any, Optional
from sqlalchemy import delete
from services.mysql.model import DfEngineSettingLogs, DfEngineSettings
from services.repository.base import BaseRepository


class AdminSettingRepository(BaseRepository):
    async def get_setting(
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
    ) -> Any:
        """Get setting row(s) with `value` already JSON-decoded (`None` when empty).

        Rows lacking a `value` key (custom `columns`) are returned untouched.
        """
        result = await self._get(
            DfEngineSettings,
            (DfEngineSettings.key, DfEngineSettings.value),
            "admin_setting_not_found",
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
        )
        for row in result if isinstance(result, list) else [result]:
            if isinstance(row, dict) and "value" in row:
                row["value"] = json.loads(row["value"]) if row["value"] else None
        return result

    async def get_setting_log(
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
        """Get setting log row(s). Whole rows are returned unless `columns` is given."""
        return await self._get(
            DfEngineSettingLogs,
            (),
            "setting_log_not_found",
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

    async def update(self, filters: tuple[Any, ...], values: dict[str, Any]) -> None:
        await self._update(DfEngineSettings, filters, values)

    async def create(self, rows: list[dict[str, Any]]) -> None:
        """Queue new setting rows. Doesn't commit."""
        self.db.add_all([DfEngineSettings(**row) for row in rows])

    async def delete(self, filters: tuple[Any, ...]) -> None:
        """Delete matching setting rows. Doesn't commit. `filters` is required, so the table can't be emptied."""
        await self.db.execute(delete(DfEngineSettings).where(*filters))

    async def create_setting_log(self, values: dict[str, Any]) -> None:
        """Queue one history entry. Doesn't commit."""
        self.db.add(DfEngineSettingLogs(**values))
