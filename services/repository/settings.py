import json
from typing import Any, Optional
from services.mysql.model import DfEngineSettings
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
            "global_setting_not_configured",
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

    async def update(self, filters: tuple[Any, ...], values: dict[str, Any]) -> None:
        await self._update(DfEngineSettings, filters, values)
