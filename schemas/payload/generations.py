from pydantic import BaseModel, Field, HttpUrl, model_validator
from typing import Literal, Optional
from uuid import UUID


class GenerationReferences(BaseModel):
    file_uid: Optional[UUID] = Field(default=None, description="File UID either from generated or uploaded by user.")
    format_udin_url: Optional[HttpUrl] = Field(default=None, description="Streamed file from DiVA.")
    type: Literal["diva", "upload", "generated"]


class ImageGenerationsPayload(BaseModel):
    model_uid: UUID = Field(default=UUID("e440a822-5ada-4ea5-99d9-92f0d38edf96"), description="Model UID.")
    menu_uid: UUID = Field(default=UUID("1977607c-400f-4356-9692-46fbcfa889f0"), description="Menu UID")
    feature_uids: list[UUID] = Field(
        default=[UUID("f4cda7d6-3b9e-4643-9571-3b317f33e033"), UUID("d2fd7093-2809-4ac8-a738-5711e7e3bcad")],
        description="Feature UIDs",
    )
    references: list[GenerationReferences] = Field(default_factory=list, description="Generation references.")
    type: Literal["image", "video"] = Field("image", description="Target generation types.")

    @model_validator(mode="after")
    def check_references(self):
        errors = []
        for idx, ref in enumerate(self.references):
            if ref.type == "diva" and ref.format_udin_url is None:
                errors.append(f"references.{idx}: format_udin_url cannot be null when type is 'diva'")
            if ref.type in ("upload", "generated") and ref.file_uid is None:
                errors.append(f"references.{idx}: file_uid cannot be null when type is '{ref.type}'")
        if errors:
            raise ValueError(", ".join(errors))
        return self
