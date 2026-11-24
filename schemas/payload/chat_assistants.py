from pydantic import BaseModel, Field, field_validator, model_validator
from schemas.payload.base import Attachment
from uuid import UUID
from error import DataValidationError
from error import DataValidationError
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
    def check_attachments_mentioned(self):
        content = self.content.lower()
        errors = {
            f"attachments.{idx}": ["reference_not_in_prompt"]
            for idx, a in enumerate(self.attachments)
            if str(a.file_uid) not in content
        }
        if errors:
            raise DataValidationError(message="reference_not_in_prompt", error=errors)
        return self


class CreateNewSessionPayload(ChatMessagePayload):
    menu_uid: UUID = Field(...)
    feature_uid: UUID = Field(...)


class ContinueSessionPayload(ChatMessagePayload):
    pass


class UpdateSessionPayload(BaseModel):
    topic: str = Field(..., min_length=1, max_length=255)
