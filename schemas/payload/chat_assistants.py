from pydantic import BaseModel, Field, model_validator
from schemas.payload.base import Attachment


class CreateNewSessionPayload(BaseModel):
    content: str = Field(..., min_length=1)
    attachments: list[Attachment] = Field(default_factory=list)

    @model_validator(mode="after")
    def dedupe_attachments(self):
        by_type = {}
        for a in self.attachments:
            by_type.setdefault(a.type, {}).setdefault(a.file_uid, a)
        self.attachments = [a for group in by_type.values() for a in group.values()]
        return self
