from typing import Any, Optional
from pydantic import Field
from schemas.format.base import TimezoneMeta, UserMeta
from utils.formatter import format_user_employees


class SettingLogRecord(TimezoneMeta):
    uid: str = Field(...)
    user_email: Optional[str] = Field(None)
    user_name: Optional[str] = Field(None)
    previous_data: Optional[dict[str, Any]] = Field(None)
    incoming_data: dict[str, Any] = Field(...)
    ip_address: Optional[str] = Field(None)
    user_agent: Optional[str] = Field(None)
    creator: Optional[UserMeta] = Field(None)
    changed_fields: list[str] = Field(...)

    # Excluded keys
    updated_at: Optional[str] = Field(default=None, exclude=True)
    archieved_at: Optional[str] = Field(default=None, exclude=True)
    favourited_at: Optional[str] = Field(default=None, exclude=True)

    @classmethod
    def format(cls, result: dict[str, Any]):
        previous_data = result.get("previous_data") or {}
        incoming_data = result.get("incoming_data") or {}
        return super().format(
            {
                **result,
                "creator": format_user_employees(result.get("created_by_user")),
                "changed_fields": sorted(
                    key
                    for key in (previous_data.keys() | incoming_data.keys())
                    if previous_data.get(key) != incoming_data.get(key)
                ),
            }
        )
