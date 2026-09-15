from pydantic import BaseModel, Field, HttpUrl, model_validator
from typing import Literal, Optional
from uuid import UUID


class GenerationReferences(BaseModel):
    file_uid: Optional[UUID] = Field(default=None, description="File UID either from generated or uploaded by user.")
    file_url: Optional[HttpUrl] = Field(default=None, description="Streamed file from DiVA.")
    type: Literal["diva", "upload", "generated"]


class ImageGenerationsPayload(BaseModel):
    model_uid: UUID = Field(description="Model UID.")
    menu_uid: UUID = Field(description="Menu UID")
    feature_uids: list[UUID] = Field(description="Feature UIDs")
    references: list[GenerationReferences]

    @model_validator(mode="after")
    def check_references(self):
        errors = []
        for idx, ref in enumerate(self.references):
            if ref.type == "diva" and ref.file_url is None:
                errors.append(f"references.{idx}: file_url cannot be null when type is 'diva'")
            if ref.type in ("upload", "generated") and ref.file_uid is None:
                errors.append(f"references.{idx}: file_uid cannot be null when type is '{ref.type}'")
        if errors:
            raise ValueError(", ".join(errors))
        return self
