import re
from pydantic import BaseModel, Field, field_validator, model_validator
from schemas.payload.base import Attachment
from uuid import UUID
from typing import Any


class ChatMessagePayload(BaseModel):
    content: str = Field(..., min_length=1)
    attachments: list[Attachment] = Field(default_factory=list)
    params: dict[str, Any] = Field({})

    @model_validator(mode="after")
    def dedupe_attachments(self):
        by_type = {}
        for a in self.attachments:
            by_type.setdefault(a.type, {}).setdefault(a.file_uid, a)
        self.attachments = [a for group in by_type.values() for a in group.values()]
        return self

    @model_validator(mode="after")
    def tag_attachments(self):
        """Every attached file named in the text becomes `<refer to {uid}>`, so the stored text always has one pattern."""
        for a in self.attachments:
            uid = str(a.file_uid)
            self.content = re.sub(
                rf"(?<!<refer to ){re.escape(uid)}(?!>)", f"<refer to {uid}>", self.content, flags=re.IGNORECASE
            )
        return self


class CreateNewSessionPayload(ChatMessagePayload):
    menu_uid: UUID = Field(...)


class ContinueSessionPayload(ChatMessagePayload):
    generate_prompt: bool = Field(
        default=False, description="Set to true when the user says yes to writing the prompt now."
    )


class UpdateSessionPayload(BaseModel):
    topic: str = Field(..., min_length=1, max_length=255)
