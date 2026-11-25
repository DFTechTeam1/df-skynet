from typing import Literal, Optional
from pydantic import BaseModel, field_validator, Field
from apps.secret import BASE_URL
from schemas.format.action import ChatAssistantAction
from schemas.format.files import ICON_COLOR_MAP
from utils.formatter import format_datetime
from typing import Any, Optional
from services.mysql.model import DfEngineModelOptions
from services.repository.base import BaseRepository


class ModelOptionRepository(BaseRepository):
    async def get_model(
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
            DfEngineModelOptions,
            (),
            "model_option_not_found",
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

    async def upsert(self, rows: list[dict[str, Any]], keep_columns: tuple[str, ...]) -> None:
        await self._upsert(DfEngineModelOptions, rows, keep_columns)

    async def update(self, filters: tuple[Any, ...], values: dict[str, Any]) -> None:
        await self._update(DfEngineModelOptions, filters, values)
