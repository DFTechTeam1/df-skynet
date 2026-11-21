from typing import Any, Optional
from pydantic import BaseModel, Field
from utils.formatter import format_datetime


class TimezoneMeta(BaseModel):
    created_at: Optional[str] = Field(default=None)
    updated_at: Optional[str] = Field(default=None)
    archieved_at: Optional[str] = Field(default=None)

    @classmethod
    def format(cls, result: dict[str, Any]):
        return cls(
            **{
                **result,
                "created_at": format_datetime(result["created_at"]),
                "updated_at": format_datetime(result.get("updated_at")),
                "archieved_at": format_datetime(result.get("archieved_at")),
            }
        )


class ActionMeta(BaseModel):
    can_fetch_detail: bool = Field(default=True)
    can_set_archieve: bool = Field(default=True)
    can_update: bool = Field(default=True)
