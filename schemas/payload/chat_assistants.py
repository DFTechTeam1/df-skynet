from pydantic import BaseModel, Field, field_validator, model_validator
from schemas.payload.base import Attachment
from uuid import UUID
from typing import Any


class CreateNewSessionPayload(BaseModel):
    menu_uid: UUID = Field(...)
    feature_uid: UUID = Field(...)
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


class UpdateSessionPayload(BaseModel):
    topic: str = Field(..., min_length=1, max_length=255)
