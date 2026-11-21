from typing import Any
from pydantic import BaseModel, Field
from schemas.format.base import ActionMeta, TimezoneMeta
from utils.formatter import format_udin_url


class ChatSession(TimezoneMeta):
    uid: str = Field(...)
    topic: str = Field(...)
    action: ActionMeta = Field(default_factory=ActionMeta)

    @classmethod
    def format(cls, result: dict[str, Any]):
        session = super().format(result)
        session.action.can_set_archieve = result.get("archieved_at") is None
        return session


class ChatAttachment(BaseModel):
    uid: str = Field(...)
    name: str = Field(...)
    type: str = Field(...)
    path: str = Field(...)

    @classmethod
    def format(cls, attachment: dict[str, Any]) -> "ChatAttachment":
        file = attachment["upload_file"] or attachment["generation_result"]
        return cls(
            type="upload" if attachment["upload_file"] else "generated",
            uid=file["uid"],
            name=file["name"],
            path=format_udin_url(file["path"]),
        )


class ChatMessage(BaseModel):
    uid: str = Field(...)
    content: str = Field(...)
    sender: str = Field(...)
    chat_attachments: list[ChatAttachment] = Field(default_factory=list)

    @classmethod
    def format(cls, result: dict[str, Any]) -> "ChatMessage":
        return cls(
            uid=result["uid"],
            content=result["content"],
            sender=result["sender"],
            chat_attachments=[ChatAttachment.format(ref["attachment"]) for ref in result.get("chat_references", [])],
        )
