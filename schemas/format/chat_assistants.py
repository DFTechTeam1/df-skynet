import re
from typing import Any, Optional
from pydantic import BaseModel, Field
from schemas.format.base import ActionMeta, TimezoneMeta
from schemas.format.openrouter import Attachment, Message
from utils.formatter import format_udin_url


FENCE = re.compile(r"```[^\n]*\n(.*?)\n?```", re.DOTALL)


class MessageAction(BaseModel):
    can_resend: bool = False


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
    status_code: int = Field(...)
    has_generation_prompt: bool = Field(default=False)
    generation_prompt: Optional[str] = Field(
        default=None, description="Copy-paste ready prompt, only when has_generation_prompt."
    )
    chat_attachments: list[ChatAttachment] = Field(default_factory=list)
    action: MessageAction

    @classmethod
    def format(cls, result: dict[str, Any]) -> "ChatMessage":
        has_prompt = bool(result.get("has_generation_prompt"))
        attachments = [ChatAttachment.format(ref["attachment"]) for ref in result.get("chat_references", [])]
        fence = FENCE.search(result["content"]) if has_prompt else None
        prompt = fence.group(1).strip() if fence else None
        if prompt:
            missing = [a.uid for a in attachments if a.uid not in prompt]
            if missing:
                prompt += "\n\n" + " ".join(f"<refer to {uid}>" for uid in missing)

        status_code = result.get("status_code") or 200
        return cls(
            uid=result["uid"],
            content=result["content"],
            sender=result["sender"],
            status_code=status_code,
            action=MessageAction(can_resend=status_code != 200 and result["sender"] != "openrouter"),
            has_generation_prompt=has_prompt,
            generation_prompt=prompt,
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
