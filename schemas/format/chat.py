from typing import Literal, Optional
from pydantic import BaseModel, field_validator
from apps.secret import BASE_URL
from schemas.format.action import ChatAssistantAction
from schemas.format.files import ICON_COLOR_MAP
from utils.formatter import format_datetime


class ChatCreatedAt(BaseModel):
    created_at: Optional[str] = None

    @field_validator("created_at", mode="before")
    @classmethod
    def set_created_at(cls, v):
        try:
            return format_datetime(v)
        except ValueError:
            return v


class ChatTimezone(ChatCreatedAt):
    updated_at: Optional[str] = None
    archived_at: Optional[str] = None

    @field_validator("updated_at", "archived_at", mode="before")
    @classmethod
    def set_time(cls, v):
        try:
            return format_datetime(v)
        except ValueError:
            return v


class ChatImageUrls(BaseModel):
    """Stored relative paths (`<chat_uid>/<file>`) become public urls under the mounted chat storage."""

    images: list[str] = []

    @field_validator("images", mode="before")
    @classmethod
    def set_urls(cls, v):
        return [f"{BASE_URL.rstrip('/')}/storages/chat_assistants/{path}" for path in v or []]


class ChatAssistantItem(ChatTimezone):
    uid: str
    placeholder: str
    icon: str = ICON_COLOR_MAP["chat"]["icon"]
    color: str = ICON_COLOR_MAP["chat"]["color"]
    action: ChatAssistantAction


class ChatAssistantMessage(ChatCreatedAt, ChatImageUrls):
    role: Literal["user", "assistant"]
    text: Optional[str] = None


class ChatAssistantDetail(ChatAssistantItem):
    messages: list[ChatAssistantMessage] = []
