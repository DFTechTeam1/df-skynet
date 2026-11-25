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
        )


class ModelAction(BaseModel):
    can_enable_disable: bool = Field(True)
    can_set_as_main: bool = Field(True)
    can_delete: bool = Field(True)
    can_recover: bool = Field(True)


class ModelRecord(BaseModel):
    pass
