from typing import Any, Optional
from pydantic import BaseModel, Field
from schemas.format.base import ActionMeta, TimezoneMeta, UserMeta
from schemas.format.openrouter import Attachment, Message
from utils.formatter import format_datetime, format_udin_url, format_user_employees

MESSAGE_SUCCESS_STYLE = {"icon": "mdi-check-circle", "color": "green"}
MESSAGE_FAILED_STYLE = {"icon": "mdi-alert-circle", "color": "red"}
OPENROUTER_CREATOR = {
    "user_id": None,
    "nickname": "Openrouter",
    "image": "https://openrouter.ai/apple-touch-icon.png",
}


class MessageCreator(UserMeta):
    user_id: Optional[int] = Field(default=None)  # type: ignore


class MessageAction(BaseModel):
    can_resend: bool = False
    can_generate_prompt: bool = False


class ChatSessionAction(ActionMeta):
    # Excluded actions
    can_delete: bool = Field(default=True, exclude=True)


class ChatSession(TimezoneMeta):
    uid: str = Field(...)
    topic: str = Field(...)
    action: ChatSessionAction = Field(default_factory=ChatSessionAction)

    # Excluded key
    favourited_at: Optional[str] = Field(default=None, exclude=True)

    @classmethod
    def format(cls, result: dict[str, Any]):
        session = super().format(result)
        session.action.can_set_archieve = result.get("archieved_at") is None
        return session


class ProjectChatSession(ChatSession):
    creator: MessageCreator = Field(...)


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
    creator: MessageCreator = Field(...)
    status_code: int = Field(...)
    sent_at: Optional[str] = Field(default=None)
    icon: str = Field(...)
    color: str = Field(...)
    has_generation_prompt: bool = Field(default=False)
    will_generate_prompt: bool = Field(default=False)
    chat_attachments: list[ChatAttachment] = Field(default_factory=list)
    action: MessageAction

    @classmethod
    def format(cls, result: dict[str, Any]) -> "ChatMessage":
        has_prompt = bool(result.get("has_generation_prompt"))
        will_prompt = bool(result.get("will_generate_prompt"))
        attachments = [ChatAttachment.format(ref["attachment"]) for ref in result.get("chat_references", [])]

        status_code = result.get("status_code") or 200
        user = format_user_employees(result.get("created_by_user"))  # None unless a user wrote the row
        return cls(
            uid=result["uid"],
            content=result["content"],
            sender=(user or {}).get("nickname") or ("User" if result.get("role") == "user" else "Openrouter"),
            creator=user or OPENROUTER_CREATOR,  # type: ignore
            status_code=status_code,
            sent_at=format_datetime(result.get("sent_at")),
            **(MESSAGE_SUCCESS_STYLE if status_code == 200 else MESSAGE_FAILED_STYLE),
            action=MessageAction(
                can_resend=status_code != 200 and user is not None,
                can_generate_prompt=will_prompt and user is None and status_code == 200,
            ),
            has_generation_prompt=has_prompt,
            will_generate_prompt=will_prompt,
            chat_attachments=attachments,
        )


def build_history(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    system = [Message.build("system", r["content"]).to_payload() for r in rows if r["role"] == "system"]
    turns = []
    for r in rows:
        if r["role"] == "system" or (r.get("status_code") or 200) != 200:
            continue
        attachments = [
            Attachment(uid=a.uid, url=a.path, source=a.type)  # type: ignore
            for a in (ChatAttachment.format(ref["attachment"]) for ref in r.get("chat_references", []))
        ]
        turns.append(Message.build(r["role"], r["content"], attachments).to_payload())  # type: ignore
    return system + turns
