from typing import Any, Optional
from services.mysql.model import DfEngineMenus
from services.repository.base import BaseRepository


class MenuRepository(BaseRepository):
    async def get_menu(
        self,
        filters: Optional[tuple[Any, ...]] = None,
        columns: Optional[tuple[Any, ...]] = None,
        options: Optional[tuple[Any, ...]] = None,
        joins: Optional[tuple[Any, ...]] = None,
        raise_if_null: bool = True,
        context: Optional[dict[str, Any]] = None,
        fetch_one: bool = True,
        limit: Optional[int] = None,
    ) -> Any:
        return await self._get(
            DfEngineMenus,
            (DfEngineMenus.name,),
            "menu_not_found",
            filters,
            columns,
            options,
            joins,
            raise_if_null,
            context,
            fetch_one,
            limit,
        )
