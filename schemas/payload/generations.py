from pydantic import BaseModel, Field, HttpUrl, model_validator
from typing import Any, Literal, Optional
from uuid import UUID
from error import DataValidationError


class GenerationReferences(BaseModel):
    file_uid: Optional[UUID] = Field(default=None, description="File UID either from generated or uploaded by user.")
    diva_url: Optional[HttpUrl] = Field(default=None, description="Streamed file from DiVA.")
    type: Literal["diva", "upload", "generated"]


class FrameImageReferences(GenerationReferences):
    frame_type: Literal["first_frame", "last_frame"]


class EditImageGenerationPayload(BaseModel):
    prompt: str = Field(min_length=1, description="User prompts.")
    enhance_uid: Optional[UUID] = Field(None, description="Enhancer UID.")
    model_uid: UUID = Field(default=UUID("e440a822-5ada-4ea5-99d9-92f0d38edf96"), description="Model UID.")
    menu_uid: UUID = Field(default=UUID("1977607c-400f-4356-9692-46fbcfa889f0"), description="Menu UID.")
    feature_uid: UUID = Field(
        default=UUID("f4cda7d6-3b9e-4643-9571-3b317f33e033"),
        description="Feature UID.",
    )
    references: list[GenerationReferences] = Field(default_factory=list, description="Generation references.")
    parameter: dict[str, Any] = Field(description="Dynamic parameter based on target model.")
    x_min: Optional[float] = Field(default=None, ge=0, le=1, description="Focus area left bound (0-1).")
    x_max: Optional[float] = Field(default=None, ge=0, le=1, description="Focus area right bound (0-1).")
    y_min: Optional[float] = Field(default=None, ge=0, le=1, description="Focus area top bound (0-1).")
    y_max: Optional[float] = Field(default=None, ge=0, le=1, description="Focus area bottom bound (0-1).")

    @model_validator(mode="after")
    def dedupe_references(self):
        deduped: dict[tuple[str, str], GenerationReferences] = {}
        for ref in self.references:
            uid = str(ref.diva_url) if ref.type == "diva" else str(ref.file_uid)
            deduped[(ref.type, uid)] = ref
        self.references = list(deduped.values())
        return self

    @model_validator(mode="after")
    def check_references(self):
        errors: dict[str, list[str]] = {}
        for idx, ref in enumerate(self.references):
            if ref.type == "diva" and ref.diva_url is None:
                errors[f"references.{idx}"] = ["reference_diva_url_required"]
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

        if len(filled) != len(area):
            errors = {key: ["generation_area_incomplete"] for key in area if area[key] is None}
            raise DataValidationError(message="generation_area_incomplete", error=errors)
        return self


class ImageVideoGenerationPayload(BaseModel):
    prompt: str = Field(min_length=1, description="User prompts.")
    enhance_uid: Optional[UUID] = Field(None, description="Enhancer UID.")
    model_uid: UUID = Field(default=UUID("e440a822-5ada-4ea5-99d9-92f0d38edf96"), description="Model UID.")
    menu_uid: UUID = Field(default=UUID("1977607c-400f-4356-9692-46fbcfa889f0"), description="Menu UID.")
    feature_uid: UUID = Field(
        default=UUID("f4cda7d6-3b9e-4643-9571-3b317f33e033"),
        description="Feature UID.",
    )
    references: list[GenerationReferences] = Field(default_factory=list, description="Generation references.")
    type: Literal["image", "video"] = Field("image", description="Target generation types.")
    parameter: dict[str, Any] = Field(description="Dynamic parameter based on target model.")
    frame_images: list[FrameImageReferences] = Field(
        default_factory=list,
        min_length=0,
        max_length=2,
        description="First/last frame references. Video generations only.",
    )

    @model_validator(mode="after")
    def dedupe_references(self):
        deduped: dict[tuple[str, str], GenerationReferences] = {}
        for ref in self.references:
            uid = str(ref.diva_url) if ref.type == "diva" else str(ref.file_uid)
            deduped[(ref.type, uid)] = ref
        self.references = list(deduped.values())
        return self

    @model_validator(mode="after")
    def check_references(self):
        errors: dict[str, list[str]] = {}
        for idx, ref in enumerate(self.references):
            if ref.type == "diva" and ref.diva_url is None:
                errors[f"references.{idx}"] = ["reference_diva_url_required"]
            elif ref.type in ("upload", "generated") and ref.file_uid is None:
                errors[f"references.{idx}"] = ["reference_file_uid_required"]
        if errors:
            raise DataValidationError(message="references_invalid", error=errors)
        return self

    @model_validator(mode="after")
    def check_frame_images(self):
        if self.frame_images and self.type != "video":
            raise DataValidationError(
                message="frame_images_invalid",
                error={"frame_images": ["frame_images_requires_video_type"]},
            )

        types = [ref.type for ref in self.frame_images]
        if len(types) != len(set(types)):
            raise DataValidationError(
                message="frame_images_duplicate_type",
                error={"frame_images": ["frame_images_duplicate_type"]},
            )

        errors: dict[str, list[str]] = {}
        for idx, ref in enumerate(self.frame_images):
            if ref.type == "diva" and ref.diva_url is None:
                errors[f"frame_images.{idx}"] = ["reference_diva_url_required"]
            elif ref.type in ("upload", "generated") and ref.file_uid is None:
                errors[f"frame_images.{idx}"] = ["reference_file_uid_required"]
        if errors:
            raise DataValidationError(message="references_invalid", error=errors)
        return self


class PromptEnhancerPayload(BaseModel):
    prompt: str = Field(min_length=1, description="User prompts.")
    menu_uid: UUID = Field(default=UUID("1977607c-400f-4356-9692-46fbcfa889f0"), description="Menu UID.")
    feature_uid: UUID = Field(default=UUID("f4cda7d6-3b9e-4643-9571-3b317f33e033"), description="Feature UID.")
