from pydantic import BaseModel, Field, HttpUrl, model_validator
from typing import Any, Literal, Optional
from uuid import UUID

from error import DataValidationError


class GenerationReferences(BaseModel):
    file_uid: Optional[UUID] = Field(default=None, description="File UID either from generated or uploaded by user.")
    format_udin_url: Optional[HttpUrl] = Field(default=None, description="Streamed file from DiVA.")
    type: Literal["diva", "upload", "generated"]


class GenerationsPayload(BaseModel):
    prompt: str = Field(min_length=1, description="User prompts.")
    enhance_uid: Optional[UUID] = Field(None, description="Enhancer UID.")
    model_uid: UUID = Field(default=UUID("e440a822-5ada-4ea5-99d9-92f0d38edf96"), description="Model UID.")
    menu_uid: UUID = Field(default=UUID("1977607c-400f-4356-9692-46fbcfa889f0"), description="Menu UID.")
    feature_uid: UUID = Field(
        default=UUID("f4cda7d6-3b9e-4643-9571-3b317f33e033"),
        description="Feature UID.",
    )
    references: list[GenerationReferences] = Field(default_factory=list, description="Generation references.")
    type: Literal["image", "video", "image_edit"] = Field("image", description="Target generation types.")
    parameter: dict[str, Any] = Field(description="Dynamic parameter based on target model.")
    x_min: Optional[float] = Field(default=None, ge=0, le=1, description="Focus area left bound (0-1).")
    x_max: Optional[float] = Field(default=None, ge=0, le=1, description="Focus area right bound (0-1).")
    y_min: Optional[float] = Field(default=None, ge=0, le=1, description="Focus area top bound (0-1).")
    y_max: Optional[float] = Field(default=None, ge=0, le=1, description="Focus area bottom bound (0-1).")

    @model_validator(mode="after")
    def check_references(self):
        errors: dict[str, list[str]] = {}
        for idx, ref in enumerate(self.references):
            if ref.type == "diva" and ref.format_udin_url is None:
                errors[f"references.{idx}"] = ["reference_format_udin_url_required"]
            elif ref.type in ("upload", "generated") and ref.file_uid is None:
                errors[f"references.{idx}"] = ["reference_file_uid_required"]
        if errors:
            raise DataValidationError(message="references_invalid", error=errors)
        return self

    @model_validator(mode="after")
    def check_focus_area(self):
        area = {"x_min": self.x_min, "x_max": self.x_max, "y_min": self.y_min, "y_max": self.y_max}
        filled = [key for key, value in area.items() if value is not None]
        if not filled:
            return self

        if self.type != "image_edit":
            errors = {key: ["generation_area_image_edit_only"] for key in filled}
            raise DataValidationError(message="generation_area_image_edit_only", error=errors)

        if len(filled) != len(area):
            errors = {key: ["generation_area_incomplete"] for key in area if area[key] is None}
            raise DataValidationError(message="generation_area_incomplete", error=errors)
        return self
